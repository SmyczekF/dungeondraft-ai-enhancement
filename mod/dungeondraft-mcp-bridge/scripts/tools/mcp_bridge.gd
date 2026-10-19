# MCP Bridge — Dungeondraft mod
#
# Opens a localhost TCP server inside Dungeondraft and speaks a tiny
# newline-delimited JSON protocol (see README.md) so an external MCP server
# can drive the currently-open map for AI-assisted map building.
#
# Engine: Dungeondraft runs Godot 3.4.2, so this uses the Godot 3 networking
# class names (TCP_Server / StreamPeerTCP) and the connect(sig, self, "method")
# signal form. Mod tool scripts receive a per-frame update(delta) callback but
# NOT _process / _input, so all socket polling happens in update().
#
# Element model: every element this bridge touches is referenced by an integer
# `id` == Dungeondraft's node_id (Global.World.AssignNodeID / GetNodeByID /
# DeleteNodeByID). Creation commands return the new id; query commands return
# ids you can pass back to move/modify/delete.
#
# Undo: reversible edits push an op onto the bridge's own undo/redo stacks
# (DD 3.4.2's History.CreateCustomRecord is unreliable); see _record_and_dispatch.

var script_class = "tool"

const HOST := "127.0.0.1"
const PORT := 8787
const BRIDGE_VERSION := "1.0.1"
const PROTOCOL_VERSION := 23
const MAX_REQUEST_BYTES := 1048576
const LISTENER_KEY := "dungeondraft_mcp.bridge_listener"

# Commands that get wrapped in a Dungeondraft undo record (see _record_and_dispatch).
const CREATE_CMDS := [
	"place_object", "draw_wall", "draw_path", "add_light",
	"add_portal", "add_roof", "add_text", "duplicate_object",
]
const TRANSFORM_CMDS := ["move_element", "modify_object"]
const TERRAIN_CMDS := ["fill_terrain", "fill_region", "paint_terrain", "paint_path"]
const CAVE_CMDS := ["dig_cave", "clear_caves"]
# Neutral opaque tint for pattern floors when no color is given. PatternShapeTool
# has no per-texture default (and its .Color leaks across calls), so we apply a
# deterministic wood/stone-neutral tone; callers pass an explicit color to override.
const DEFAULT_PATTERN_TINT := Color(0.62, 0.5, 0.34)

# SelectTool.GetSelectableType() integer -> readable kind.
const KIND_NAMES := {
	1: "wall", 2: "portal", 3: "wall_portal", 4: "object",
	5: "path", 6: "light", 7: "pattern", 8: "roof",
}
# kind string -> the Level child collection that holds those nodes.
const COLLECTIONS := {
	"objects": "Objects", "walls": "Walls", "lights": "Lights",
	"paths": "Pathways", "portals": "Portals", "roofs": "Roofs", "patterns": "PatternShapes",
	"texts": "Texts",
}

var _server : TCP_Server = null
var _conns := []         # array of { "peer": StreamPeerTCP, "buf": String }
var _undo_stack := []    # bridge-managed undo ops (see _build_op / _apply_op)
var _redo_stack := []
var _pending_switch := {}
var _edit_sequence := 0
var _unrecorded_revision := 0
var _saved_state_signature := "[0,[]]"
var _save_sequence := 0
var _pending_save_checkpoint := {}
var _instance_id := ""
var _asset_catalog := {}
var _catalog_version := ""
var _export_state := {}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

func start():
	_instance_id = str(OS.get_ticks_msec()) + "-" + str(randi())
	_register_tool()
	# Dungeondraft has no tool-mod stop callback and can retain the previous
	# script during UI map switches. Explicitly retire its transport before bind.
	# Store the native TCP_Server ID, not a mod-script object: this Mono build
	# cannot safely marshal a previous GDScript tool instance back from metadata.
	# Engine survives map/editor replacement; Editor metadata does not.
	if Engine.has_meta(LISTENER_KEY):
		var previous_server = instance_from_id(int(Engine.get_meta(LISTENER_KEY)))
		if previous_server is TCP_Server:
			previous_server.stop()
	_server = TCP_Server.new()
	var err = _server.listen(PORT, HOST)
	if err == OK:
		Engine.set_meta(LISTENER_KEY, _server.get_instance_id())
		print("[mcp-bridge] listening on %s:%d (protocol v%d)" % [HOST, PORT, PROTOCOL_VERSION])
	else:
		_server = null
		print("[mcp-bridge] FAILED to listen on %s:%d (error %d); bridge unavailable" % [HOST, PORT, err])


func _stop_listener():
	if _server != null:
		_server.stop()
	_server = null
	for connection in _conns:
		connection["peer"].disconnect_from_host()
	_conns = []


func update(delta : float):
	_refresh_export()
	if _server == null or not _server.is_listening():
		return

	while _server.is_connection_available():
		var peer = _server.take_connection()
		peer.set_no_delay(true)
		_conns.append({ "peer": peer, "buf": "" })

	var still_open := []
	for c in _conns:
		var peer : StreamPeerTCP = c["peer"]
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			continue
		var avail = peer.get_available_bytes()
		if avail > 0:
			var res = peer.get_data(min(avail, MAX_REQUEST_BYTES + 1))   # [err, PoolByteArray]
			if res[0] == OK:
				c["buf"] += res[1].get_string_from_utf8()
		if c["buf"].to_utf8().size() > MAX_REQUEST_BYTES:
			peer.put_data((JSON.print(_err("request exceeds 1 MiB")) + "\n").to_utf8())
			peer.disconnect_from_host()
			continue
		var nl = c["buf"].find("\n")
		while nl != -1:
			var line = c["buf"].substr(0, nl).strip_edges()
			c["buf"] = c["buf"].substr(nl + 1)
			if line != "":
				_handle_line(peer, line)
			nl = c["buf"].find("\n")
		still_open.append(c)
	_conns = still_open
	_advance_batch()
	if not _pending_switch.empty():
		# A map change reloads the mod. Release the listener before the new copy
		# starts, after the current request has received its acknowledgement.
		_stop_listener()
		call_deferred("_run_pending_switch")


func _run_pending_switch():
	var action = _pending_switch
	_pending_switch = {}
	Global.Editor.call("ForceOpenMap", action["path"])


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

func _handle_line(peer : StreamPeerTCP, line : String):
	var parsed = JSON.parse(line)
	var req = parsed.result
	var resp : Dictionary
	if parsed.error != OK or typeof(req) != TYPE_DICTIONARY:
		resp = _err("invalid JSON request")
	else:
		resp = _record_and_dispatch(req)
	peer.put_data((JSON.print(resp) + "\n").to_utf8())


# Runs a command and, if it succeeded and is a reversible map edit, pushes an op
# onto the bridge-managed undo stack. We do NOT use Dungeondraft's
# History.CreateCustomRecord — on 3.4.2 it invokes undo() unreliably and never
# round-trips redo(). Our own stacks are deterministic and fully under control.
# Pre-edit state (transform / terrain splat) is captured before the command runs.
func _record_and_dispatch(req : Dictionary) -> Dictionary:
	var cmd = req.get("cmd", "")
	if bool(_master().get("IsExporting")) and (not cmd in BATCH_READ_COMMANDS or cmd == "apply_batch"):
		return _err("native export is active; wait for get_export_status before editing")
	if _active_batch != "" and not _executing_batch and not cmd in BATCH_READ_COMMANDS:
		return _err("a batch is active; inspect or cancel it before other edits")

	var pre = null
	if cmd == "set_water_settings" and Global.World.GetCurrentLevel() != null:
		pre = _water_settings_snapshot()
	if cmd == "set_terrain_settings" and Global.World.GetCurrentLevel() != null:
		pre = _terrain_settings_data()
	if cmd == "delete_object":
		var node = _resolve(req)
		if node != null and node.get_parent() == Global.World.GetCurrentLevel().Objects:
			pre = {"kind": "delete_object", "id": int(req["id"]), "node": node, "parent": node.get_parent(), "data": node.Save(false)}
	if cmd in TRANSFORM_CMDS and req.has("id"):
		var node = Global.World.GetNodeByID(int(req["id"]))
		if node != null:
			pre = _snapshot(node)

	var terrain_before = null
	if cmd in TERRAIN_CMDS:
		var lvl = Global.World.GetCurrentLevel()
		if lvl != null:
			terrain_before = _terrain_snapshot()

	var water_before = null
	if cmd == "draw_water" and Global.World.GetCurrentLevel() != null:
		water_before = Global.World.GetCurrentLevel().WaterMesh.Save().duplicate(true)

	var cave_before = null
	if cmd in CAVE_CMDS:
		cave_before = _cave_snapshot()

	var result = _safe_dispatch(req)
	if typeof(result) == TYPE_DICTIONARY and result.get("ok", false):
		var op = _build_op(cmd, req, result, pre, terrain_before, cave_before, water_before)
		if op != null:
			_edit_sequence += 1
			op["edit_id"] = _edit_sequence
			op["level_id"] = Global.World.GetCurrentLevel().ID
			_undo_stack.append(op)
			_redo_stack = []   # a fresh edit invalidates the redo branch
		if cmd in CREATE_CMDS or cmd in TRANSFORM_CMDS or cmd in TERRAIN_CMDS or cmd in CAVE_CMDS or cmd in ["draw_water", "delete_object", "set_water_settings", "set_terrain_settings"] or cmd in ["delete_element", "place_pattern", "build_room", "set_terrain_slot", "add_level", "undo", "redo"]:
			if op == null and not cmd in ["undo", "redo"]:
				_unrecorded_revision += 1
	return result


# Returns an undo op for a recordable command, or null. Ops are reversed by
# _apply_op (undo=true) and re-applied (undo=false).
func _build_op(cmd, req, result, pre, terrain_before, cave_before = null, water_before = null):
	if cmd in CREATE_CMDS:
		var id = result["result"].get("id", -1)
		if id != null and int(id) >= 0:
			var node = Global.World.GetNodeByID(int(id))
			if node != null:
				if cmd in ["place_object", "duplicate_object"]:
					return { "kind": "create_object", "node": node, "parent": node.get_parent(), "id": int(id), "data": node.Save(false) }
				return { "kind": "create", "node": node, "parent": node.get_parent(), "id": int(id) }
	elif cmd == "delete_object" and pre != null:
		pre["node"] = null
		return pre
	elif cmd == "set_water_settings" and pre != null:
		return {"kind": "water_settings", "before": pre, "after": _water_settings_snapshot()}
	elif cmd == "set_terrain_settings" and pre != null:
		return {"kind": "terrain_settings", "before": pre, "after": _terrain_settings_data()}
	elif cmd in TRANSFORM_CMDS and pre != null:
		var node = Global.World.GetNodeByID(int(req["id"]))
		if node != null:
			return { "kind": "transform", "id": int(req["id"]), "old": pre, "new": _snapshot(node) }
	elif cmd in TERRAIN_CMDS and terrain_before != null:
		var lvl = Global.World.GetCurrentLevel()
		if lvl != null:
			return { "kind": "terrain", "before": terrain_before, "after": _terrain_snapshot() }
	elif cmd == "draw_water" and water_before != null:
		return {"kind": "water", "before": water_before, "after": Global.World.GetCurrentLevel().WaterMesh.Save().duplicate(true), "points": _points(req["points"])}
	elif cmd in CAVE_CMDS and cave_before != null:
		var after = _cave_snapshot()
		if after != null:
			return { "kind": "cave", "before": cave_before, "after": after }
	return null


func _do_undo() -> Dictionary:
	if _undo_stack.empty():
		return _ok({ "undone": false, "reason": "nothing to undo" })
	var op = _undo_stack.back()
	if not _apply_op(op, true):
		return _err("cannot undo: return to the original floor and ensure its element is available")
	_undo_stack.pop_back()
	_redo_stack.append(op)
	return _ok({ "undone": true, "kind": op["kind"], "undo_depth": _undo_stack.size() })


func _do_redo() -> Dictionary:
	if _redo_stack.empty():
		return _ok({ "redone": false, "reason": "nothing to redo" })
	var op = _redo_stack.back()
	if not _apply_op(op, false):
		return _err("cannot redo: return to the original floor and ensure its element and asset are available")
	_redo_stack.pop_back()
	_undo_stack.append(op)
	return _ok({ "redone": true, "kind": op["kind"], "redo_depth": _redo_stack.size() })


func _apply_op(op, undo : bool) -> bool:
	if Global.World.GetCurrentLevel() == null or Global.World.GetCurrentLevel().ID != op["level_id"]:
		return false
	match op["kind"]:
		"delete_object":
			var level = Global.World.GetCurrentLevel()
			if level == null or not is_instance_valid(op["parent"]) or op["parent"] != level.Objects:
				return false
			if undo:
				if Global.World.HasNodeID(int(op["id"])):
					return false
				op["node"] = level.Objects.LoadObject(op["data"])
				return op["node"] != null
			var node = Global.World.GetNodeByID(int(op["id"]))
			if node == null or node.get_parent() != level.Objects:
				return false
			_deselect_node(node)
			_detach_node(node, int(op["id"]))
			node.queue_free()
			op["node"] = null
		"create_object":
			# Prop._ExitTree removes its native search-table entry. Reattaching the
			# same Prop recreates render children but leaves that entry stale.
			# Restore a fresh Prop through the native serializer instead.
			var level = Global.World.GetCurrentLevel()
			if level == null or not is_instance_valid(op["parent"]) or op["parent"] != level.Objects:
				return false
			if undo:
				var node = op["node"]
				if not is_instance_valid(node) or node.get_parent() != level.Objects:
					return false
				op["data"] = node.Save(false)
				_deselect_node(node)
				_detach_node(node, int(op["id"]))
				node.queue_free()
				op["node"] = null
			else:
				if Global.World.HasNodeID(int(op["id"])):
					return false
				var restored = level.Objects.LoadObject(op["data"])
				if restored == null:
					return false
				op["node"] = restored
		"create":
			if undo:
				_detach_node(op["node"], int(op["id"]))
			else:
				_attach_node(op["node"], op["parent"], int(op["id"]))
		"transform":
			if not Global.World.HasNodeID(int(op["id"])):
				return false
			_apply_props(Global.World.GetNodeByID(int(op["id"])), op["old"] if undo else op["new"])
		"water":
			var mesh = Global.World.GetCurrentLevel().WaterMesh
			var data = op["before"] if undo else op["after"]
			if data.has("tree"):
				mesh.Load(data)
			else:
				mesh.DrawPolygon(op["points"], true)
		"terrain":
			_restore_splat(op["before"] if undo else op["after"])
		"terrain_settings":
			_apply_terrain_settings(op["before"] if undo else op["after"])
		"water_settings":
			_restore_water_settings(op["before"] if undo else op["after"])
		"cave":
			_restore_cave(op["before"] if undo else op["after"])
	return true


func _detach_node(node, id : int):
	if is_instance_valid(node) and node.get_parent() != null:
		node.get_parent().remove_child(node)
	if Global.World.HasNodeID(id):
		Global.World.RemoveNodeID(id)


func _attach_node(node, parent, id : int):
	if not is_instance_valid(node):
		return
	if node.get_parent() == null and is_instance_valid(parent):
		parent.add_child(node)
	Global.World.SetNodeID(node, id)
	if node.has_method("RemakeLines"):
		node.RemakeLines()   # walls/paths cache geometry; refresh after re-adding


func _set_object_layer(node, layer : int):
	if node.z_index == layer:
		return
	var objects = Global.World.GetCurrentLevel().Objects
	# The native selection search buckets are keyed by ZIndex. Remove at the
	# old layer, then register at the new layer, including undo/redo.
	objects.RemoveFromSearchTable(node)
	node.z_index = layer
	objects.AddToSearchTable(node, false)


func _apply_props(node, snap):
	if node == null or snap == null:
		return
	if snap.get("texture") != null and node.has_method("SetTexture"):
		node.SetTexture(snap["texture"])
	if snap.has("object_layer"):
		_set_object_layer(node, int(snap["object_layer"]))
	if snap.get("position") != null:
		node.position = snap["position"]
	if snap.get("rotation") != null:
		node.rotation = snap["rotation"]
	if snap.get("scale") != null:
		node.scale = snap["scale"]
	if snap.get("shadow") != null:
		node.set("HasShadow", snap["shadow"])
	if snap.get("color") != null and node.has_method("SetCustomColor"):
		node.SetCustomColor(snap["color"])


func _terrain_snapshot() -> Dictionary:
	var terrain = Global.World.GetCurrentLevel().Terrain
	var textures := []
	for i in range(terrain.textures.size()):
		textures.append(terrain.GetTexture(i))
	return {"image": terrain.CloneSplatImage(), "image2": terrain.CloneSplatImage2() if terrain.ExpandedSlots else null, "textures": textures, "settings": _terrain_settings_data()}


func _restore_splat(snapshot):
	if snapshot == null or Global.World.GetCurrentLevel() == null:
		return
	var terrain = Global.World.GetCurrentLevel().Terrain
	for i in range(snapshot["textures"].size()):
		terrain.SetTexture(snapshot["textures"][i], i)
	if snapshot["image2"] != null:
		terrain.RestoreSplat2(snapshot["image"], snapshot["image2"])
	else:
		terrain.RestoreSplat(snapshot["image"])
	terrain.UpdateSplat()
	if snapshot.has("settings"):
		_apply_terrain_settings(snapshot["settings"])


# Deep-copy the cave BitMap for the undo stack (Resource.duplicate(true) so the
# snapshot isn't aliased to the live bitmap). Returns null if no cave is present.
func _cave_snapshot():
	var cave = _cave_mesh()
	if cave == null or not cave.has_method("get_Bitmap"):
		return null
	var bm = cave.call("get_Bitmap")
	if bm == null:
		return null
	return bm.duplicate(true)


# Restore a snapshotted cave BitMap and rebuild the mesh (mirror of _restore_splat
# for the cave layer). A duplicate(true) of the stored snapshot is pushed so the
# op's snapshot stays pristine across repeated undo/redo.
func _restore_cave(bm):
	if bm == null:
		return
	var cave = _cave_mesh()
	if cave == null or not cave.has_method("SetBitmap"):
		return
	cave.call("SetBitmap", bm.duplicate(true))
	if cave.has_method("FinalizeMeshAndBorders"):
		cave.call("FinalizeMeshAndBorders")
	cave.call("UpdateMesh")


func _snapshot(node) -> Dictionary:
	var s := {}
	if node.get_parent() == Global.World.GetCurrentLevel().Objects:
		s["texture"] = node.get("Texture")
	if node is Node2D:
		s["position"] = node.position
		s["rotation"] = node.rotation
		s["scale"] = node.scale
	if node.get("HasShadow") != null:
		s["shadow"] = node.get("HasShadow")
	if node.has_method("HasCustomColor") and node.HasCustomColor():
		s["color"] = node.GetCustomColor()
	if node.get_parent() == Global.World.GetCurrentLevel().Objects:
		s["object_layer"] = node.z_index
	return s


# Dispatch known commands. Handlers validate inputs before calling DD methods;
# GDScript has no exception handler for runtime errors.
func _safe_dispatch(req : Dictionary) -> Dictionary:
	var cmd = req.get("cmd", "")
	match cmd:
		# --- read / query ---
		"get_surface_state": return _surface_state()
		"get_export_status":
			_refresh_export()
			return _ok({"exporting": bool(_master().get("IsExporting")), "managed_export": not _export_state.empty(), "grid": Global.Editor.GridToggle.pressed, "lighting": Global.Editor.LightingToggle.pressed})
		"delete_object": return _delete_object(req)
		"get_water": return _ok({"level_id": Global.World.GetCurrentLevel().ID, "data": Global.World.GetCurrentLevel().WaterMesh.Save()})
		"get_water_settings": return _get_water_settings()
		"set_water_settings": return _set_water_settings(req)
		"get_terrain_settings": return _get_terrain_settings()
		"set_terrain_settings": return _set_terrain_settings(req)
		"ping": return _ok({ "pong": true, "protocol": PROTOCOL_VERSION, "bridge_version": BRIDGE_VERSION, "bridge_instance": _instance_id, "engine": Engine.get_version_info() })
		"get_status": return _get_status()
		"get_map_info": return _get_map_info()
		"get_capabilities": return _get_capabilities()
		"refresh_asset_catalog": return _refresh_asset_catalog()
		"list_asset_metadata": return _list_asset_metadata(req)
		"open_map": return _open_map(req)
		"resize_map": return _resize_map(req)
		"save_map": return _save_map(req)
		"confirm_save": return _confirm_save(req)
		"apply_batch": return _apply_batch(req)
		"get_batch": return _get_batch(req)
		"cancel_batch": return _cancel_batch(req)
		"list_asset_categories": return _ok({ "categories": ASSET_CATEGORIES })
		"list_assets": return _list_assets(req)
		"list_elements": return _list_elements(req)
		"get_element": return _get_element(req)
		"list_levels": return _list_levels()
		"dig_cave": return _dig_cave(req)
		"clear_caves": return _clear_caves(req)
		# --- create ---
		"place_object": return _place_object(req)
		"draw_wall": return _draw_wall(req)
		"draw_path": return _draw_path(req)
		"add_light": return _add_light(req)
		"add_portal": return _add_portal(req)
		"add_roof": return _add_roof(req)
		"add_text": return _add_text(req)
		"place_pattern": return _place_pattern(req)
		"build_room": return _build_room(req)
		# --- terrain ---
		"set_terrain_slot": return _set_terrain_slot(req)
		"fill_terrain": return _fill_terrain(req)
		"draw_water": return _draw_water(req)
		"fill_region": return _fill_region(req)
		"paint_terrain": return _paint_terrain(req)
		"paint_path": return _paint_path(req)
		# --- modify / delete ---
		"move_element": return _move_element(req)
		"modify_object": return _modify_object(req)
		"duplicate_object": return _duplicate_object(req)
		"delete_element": return _delete_element(req)
		# --- levels ---
		"add_level": return _add_level(req)
		"set_level": return _set_level(req)
		# --- capture ---
		"screenshot": return _screenshot(req)
		"export_map": return _export_map(req)
		# --- camera ---
		"get_camera": return _get_camera()
		"set_camera": return _set_camera(req)
		"focus_element": return _focus_element(req)
		"fit_elements": return _fit_elements(req)
		# --- history (bridge-managed undo/redo of the model's own edits) ---
		"undo": return _do_undo()
		"redo": return _do_redo()
		# --- selection ---
		"select_elements": return _select_elements(req)
		"clear_selection": return _clear_selection()
		_: return _err("unknown cmd: " + str(cmd))


const ASSET_CATEGORIES := [
	"Objects", "Walls", "Paths", "Terrain", "Lights", "Portals", "Roofs",
	"Patterns", "Patterns Colorable", "Caves", "Materials",
	"Simple Tiles", "Smart Tiles", "Smart Tiles Double",
]
const SUPPORTED_COMMANDS := [
	"get_water_settings", "set_water_settings", "get_terrain_settings", "set_terrain_settings",
	"ping", "get_status", "get_map_info", "get_capabilities", "refresh_asset_catalog",
	"list_asset_categories", "list_assets", "list_asset_metadata", "list_elements", "get_element", "get_water", "get_surface_state", "get_export_status", "list_levels",
	"apply_batch", "get_batch", "cancel_batch", "open_map", "resize_map", "save_map", "confirm_save", "place_object", "draw_wall", "draw_path", "add_light",
	"add_portal", "add_roof", "add_text", "place_pattern", "build_room", "set_terrain_slot",
	"fill_terrain", "fill_region", "draw_water", "paint_terrain", "paint_path", "dig_cave", "clear_caves",
	"move_element", "modify_object", "duplicate_object", "delete_object", "delete_element", "add_level", "set_level",
	"screenshot", "export_map", "get_camera", "set_camera", "focus_element", "fit_elements",
	"undo", "redo", "select_elements", "clear_selection",
]
const SEMANTIC_TERMS := [
	"tree", "oak", "pine", "birch", "aspen", "forest", "bush", "shrub",
	"rock", "boulder", "grass", "dirt", "mud", "road", "path", "trail",
	"stream", "river", "water", "wood", "stone", "wall", "roof", "door", "window", "light",
]


# ---------------------------------------------------------------------------
# Read / query
# ---------------------------------------------------------------------------

func _master():
	return Global.Editor.get_tree().get_root().get_node("Master")


func _ensure_asset_catalog():
	if _catalog_version != "":
		return
	_asset_catalog = {}
	var signature := ""
	for category in ASSET_CATEGORIES:
		var paths := []
		var found = Script.GetAssetList(category)
		if found != null:
			for path in found:
				paths.append(str(path))
		paths.sort()
		_asset_catalog[category] = paths
		signature += category + ":" + str(paths.size()) + "\n"
		for path in paths:
			signature += path + "\n"
	var mods := []
	for mod_id in Script.GetActiveMods():
		mods.append(str(mod_id))
	mods.sort()
	for mod_id in mods:
		signature += "mod:" + mod_id + "\n"
	_catalog_version = str(signature.hash())


func _get_capabilities() -> Dictionary:
	_ensure_asset_catalog()
	var counts := {}
	for category in ASSET_CATEGORIES:
		counts[category] = _asset_catalog[category].size()
	return _ok({"protocol": PROTOCOL_VERSION, "bridge_version": BRIDGE_VERSION, "bridge_instance": _instance_id,
		"engine": Engine.get_version_info(),
		"commands": SUPPORTED_COMMANDS, "asset_catalog_version": _catalog_version,
		"batch": {"schema_version": BATCH_SCHEMA_VERSION, "commands": BATCH_FIELDS.keys(), "max_operations": MAX_BATCH_OPERATIONS, "max_jobs": MAX_BATCH_JOBS, "max_request_bytes": MAX_REQUEST_BYTES, "operations_per_frame": BATCH_OPERATIONS_PER_FRAME, "frame_budget_usec": BATCH_FRAME_BUDGET_USEC, "max_terrain_operations": 16, "max_water_operations": 16},
		"asset_counts": counts, "active_mods": Script.GetActiveMods()})


func _refresh_asset_catalog() -> Dictionary:
	_catalog_version = ""
	_ensure_asset_catalog()
	return _ok({"asset_catalog_version": _catalog_version})


func _semantic_tags(path : String) -> Array:
	var lower = path.to_lower()
	var tags := []
	for term in SEMANTIC_TERMS:
		if lower.find(term) != -1:
			tags.append(term)
	return tags


func _list_asset_metadata(req : Dictionary) -> Dictionary:
	_ensure_asset_catalog()
	var category = str(req.get("category", "Objects"))
	if not _asset_catalog.has(category):
		return _err("unknown asset category: " + category)
	var limit = int(req.get("limit", 100))
	var offset = int(req.get("offset", 0))
	if limit < 1 or limit > 200 or offset < 0:
		return _err("limit must be 1..200 and offset must be nonnegative")
	var search = str(req.get("search", "")).to_lower()
	var out := []
	var matched := 0
	for path in _asset_catalog[category]:
		if search != "" and path.to_lower().find(search) == -1:
			continue
		if matched >= offset and out.size() < limit:
			var item := {"category": category, "path": path, "tags": _semantic_tags(path)}
			var tex = _asset_tex(category, path)
			if tex != null:
				var size = tex.get_size()
				item["texture_pixels"] = _vec(size)
				if category == "Objects":
					item["nominal_footprint_woxels"] = _vec(size)
			out.append(item)
		matched += 1
	return _ok({"category": category, "catalog_version": _catalog_version, "total": _asset_catalog[category].size(),
		"matched": matched, "offset": offset, "limit": limit, "returned": out.size(), "assets": out})


func _get_map_info() -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	var current_file = Global.Editor.get("CurrentMapFile")
	var path = "" if current_file == null else str(current_file)
	var master_node = _master()
	var info := {"map_open": level != null, "path": path, "bridge_instance": _instance_id, "dirty": bool(master_node.get("IsModified")) or _state_signature() != _saved_state_signature, "editor_dirty": bool(master_node.get("IsModified")), "bridge_dirty": _state_signature() != _saved_state_signature, "exporting": bool(master_node.get("IsExporting")), "saving": bool(master_node.get("IsSaving")), "loading": bool(master_node.get("IsLoadingMap"))}
	info["process_id"] = OS.get_process_id()
	info["executable"] = OS.get_executable_path()
	info["batch_active"] = _active_batch != ""
	if level != null:
		info["size_tiles"] = [int(Global.World.WoxelDimensions.x / 256), int(Global.World.WoxelDimensions.y / 256)]
		info["size_woxels"] = _vec(Global.World.WoxelDimensions)
		info["level_id"] = level.ID
		info["level_index"] = Global.World.CurrentLevelId
		info["level_count"] = Global.World.levels.size()
	return _ok(info)


# Inspect native serialized content, including surfaces absent from element counts.
func _bootstrap_error() -> String:
	if Global.World.GetCurrentLevel() == null or Global.World.levels.size() != 1:
		return "resize_map requires a blank single-level bootstrap map"
	var data = Global.World.GetCurrentLevel().Save()
	for key in ["objects", "walls", "portals", "paths", "patterns", "lights", "texts", "materials"]:
		if not data.get(key, []).empty():
			return "resize_map rejects populated bootstrap maps: " + key
	if not data.get("roofs", {}).get("roofs", []).empty():
		return "resize_map rejects roofs"
	for key in ["polygons", "walls"]:
		if not data.get("shapes", {}).get(key, []).empty():
			return "resize_map rejects building shapes"
	if data.get("water", {}).has("tree"):
		return "resize_map rejects water geometry"
	var cave = data.get("cave", {})
	for key in ["bitmap", "entrance_bitmap"]:
		if not _bootstrap_pool(cave.get(key, ""), [0]):
			return "resize_map rejects caves or unreadable cave data"
	var terrain = data.get("terrain", {})
	if not _bootstrap_pool(terrain.get("splat", ""), [255, 0, 0, 0]):
		return "resize_map rejects terrain painting or unreadable terrain data"
	if terrain.get("expand_slots", false):
		return "resize_map requires the default four terrain slots"
	if not _bootstrap_pool(data.get("tiles", {}).get("cells", ""), [-1]):
		return "resize_map rejects tile painting or unreadable tile data"
	return ""


func _bootstrap_pool(value, expected : Array) -> bool:
	# These strings come from Level.Save(), never from a client expression.
	var values = str2var(value) if typeof(value) == TYPE_STRING and value != "" else value
	if not typeof(values) in [TYPE_RAW_ARRAY, TYPE_INT_ARRAY]:
		return false
	if values.size() == 0 or values.size() % expected.size() != 0:
		return false
	for i in range(values.size()):
		if int(values[i]) != expected[i % expected.size()]:
			return false
	return true


func _resize_map(req : Dictionary) -> Dictionary:
	for key in ["width", "height"]:
		var value = req.get(key)
		if not typeof(value) in [TYPE_INT, TYPE_REAL] or is_nan(float(value)) or is_inf(float(value)) or float(value) != floor(float(value)) or value < 1 or value > 200:
			return _err(key + " must be an integer tile count in 1..200")
	var master_node = _master()
	if bool(master_node.get("IsBusy")) or bool(master_node.get("IsSaving")) or bool(master_node.get("IsLoadingMap")):
		return _err("editor is busy; wait before resizing")
	var reason = _bootstrap_error()
	if reason != "":
		return _err(reason)
	if not master_node.has_method("ChangeMapSize"):
		return _err("native ChangeMapSize is unavailable")
	master_node.call("ChangeMapSize", 0, 0, int(req["width"]), int(req["height"]))
	_undo_stack = []
	_redo_stack = []
	_unrecorded_revision += 1
	var size := [int(Global.World.WoxelDimensions.x / 256), int(Global.World.WoxelDimensions.y / 256)]
	if size != [int(req["width"]), int(req["height"])]:
		return _err("native resize did not reach requested dimensions; inspect the map")
	return _ok({"size_tiles": size, "size_woxels": _vec(Global.World.WoxelDimensions), "undoable": false})


func _open_map(req : Dictionary) -> Dictionary:
	var path = str(req.get("path", ""))
	var file = File.new()
	if not path.is_abs_path() or not path.to_lower().ends_with(".dungeondraft_map") or not file.file_exists(path):
		return _err("path must be an existing absolute .dungeondraft_map file")
	if Global.World.GetCurrentLevel() != null and not bool(req.get("discard_current", false)):
		return _err("a map is open; set discard_current=true to replace it")
	# Native populated-map teardown can throw Prop._ExitTree exceptions even
	# when opening reports success. Reject before clearing history or switching.
	for native_level in Global.World.levels:
		for element_kind in COLLECTIONS:
			if not _elements(native_level, element_kind).empty():
				return _err("open_map requires an empty current map; save and restart Dungeondraft with the target native file instead")
	var master_node = _master()
	if bool(master_node.get("IsSaving")) or bool(master_node.get("IsLoadingMap")):
		return _err("editor is busy saving or loading")
	_pending_switch = {"kind": "open", "path": path}
	_undo_stack = []
	_redo_stack = []
	return _ok({"requested_path": path})


func _save_map(req : Dictionary) -> Dictionary:
	if Global.World.GetCurrentLevel() == null:
		return _err("no map open")
	var master_node = _master()
	if bool(master_node.get("IsSaving")) or bool(master_node.get("IsLoadingMap")):
		return _err("editor is busy saving or loading")
	var path = str(req.get("path", ""))
	if path == "":
		path = str(Global.Editor.get("CurrentMapFile"))
	if not path.is_abs_path() or not path.to_lower().ends_with(".dungeondraft_map"):
		return _err("path must be an absolute .dungeondraft_map file")
	var dir = Directory.new()
	if not dir.dir_exists(path.get_base_dir()):
		return _err("destination directory does not exist")
	var file = File.new()
	if file.file_exists(path) and not bool(req.get("overwrite", false)):
		return _err("destination exists; set overwrite=true to replace it")
	# SaveMap exposes an Action parameter that GDScript cannot marshal; its
	# optional C# argument is not callable reliably through this build's bridge.
	# The published saveButton's signal enters the normal managed save flow.
	var save_button = Global.Editor.get("saveButton")
	if not is_instance_valid(save_button) or not save_button is BaseButton:
		return _err("native save button unavailable")
	if save_button.disabled or save_button.get_signal_connection_list("pressed").empty():
		return _err("native save action unavailable or disabled")
	Global.Editor.set("CurrentMapFile", path)
	if str(Global.Editor.get("CurrentMapFile")) != path:
		return _err("editor did not accept destination path")
	_save_sequence += 1
	_pending_save_checkpoint = {"token": _save_sequence, "path": path, "state": _state_signature()}
	save_button.emit_signal("pressed")
	return _ok({"requested_path": path, "save_token": _save_sequence})

func _state_signature() -> String:
	var edit_ids := []
	for op in _undo_stack:
		edit_ids.append(op["edit_id"])
	return JSON.print([_unrecorded_revision, edit_ids])


# The Python client confirms only after validating the completed native JSON.
# Capture the request's edit state, not edits that arrive while saving.
func _confirm_save(req : Dictionary) -> Dictionary:
	if _pending_save_checkpoint.empty() or req.get("save_token") != _pending_save_checkpoint["token"]:
		return _err("save checkpoint is absent or stale")
	if bool(_master().get("IsSaving")):
		return _err("native save is still running")
	if str(Global.Editor.get("CurrentMapFile")) != _pending_save_checkpoint["path"]:
		return _err("saved map path changed before confirmation")
	_saved_state_signature = _pending_save_checkpoint["state"]
	_pending_save_checkpoint = {}
	return _ok({"bridge_dirty": _state_signature() != _saved_state_signature})


func _get_status() -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return _ok({ "map_open": false })
	var counts := {}
	for kind in COLLECTIONS:
		counts[kind] = _elements(level, kind).size()
	return _ok({
		"map_open": true,
		"level_id": Global.World.GetCurrentLevel().ID,
		"level_count": Global.World.levels.size(),
		"level_index": Global.World.CurrentLevelId,
		"map_size_woxels": [Global.World.WoxelDimensions.x, Global.World.WoxelDimensions.y],
		"map_center": [Global.World.WoxelDimensions.x * 0.5, Global.World.WoxelDimensions.y * 0.5],
		"counts": counts,
		"active_tool": Global.Editor.ActiveToolName,
	})


func _list_assets(req : Dictionary) -> Dictionary:
	_ensure_asset_catalog()
	var category = str(req.get("category", "Objects"))
	var search = str(req.get("search", "")).to_lower()
	var limit = int(req.get("limit", 100))
	var offset = int(req.get("offset", 0))
	if limit < 1 or limit > 500 or offset < 0:
		return _err("limit must be 1..500 and offset must be nonnegative")
	if not _asset_catalog.has(category):
		return _err("unknown asset category: " + str(category))
	var all = _asset_catalog[category]
	var out := []
	var matched := 0
	for path in all:
		if search != "" and str(path).to_lower().find(search) == -1:
			continue
		if matched >= offset and out.size() < limit:
			out.append(path)
		matched += 1
	return _ok({ "category": category, "catalog_version": _catalog_version, "total": all.size(), "matched": matched,
		"offset": offset, "limit": limit, "returned": out.size(), "assets": out })


# Resolve the cave editing target: enable the CaveBrush (the UI path that wires
# the mesh to the level) and return its CaveMesh, or null if unavailable.
func _cave_mesh():
	if not Global.Editor.Tools.has("CaveBrush"):
		return null
	var brush = Global.Editor.Tools["CaveBrush"]
	brush.call("Enable")
	if not brush.has_method("get_Mesh"):
		return null
	return brush.call("get_Mesh")


# Woxel position -> cave-bitmap cell (the bitmap is the woxel grid at CellSize
# woxels/cell plus a MapEdgeBuffer border).
func _cave_cell(cave, world : Vector2) -> Vector2:
	var cs = cave.call("get_CellSize")
	var buf = int(cave.get("MapEdgeBuffer"))
	return Vector2(int(floor(world.x / cs)) + buf, int(floor(world.y / cs)) + buf)


# Dig (or fill) a cave along a polyline brush stroke. The cave is a MeshInstance2D
# whose open/rock state is a Godot BitMap (true = open cave floor); editing it
# then SetBitmap + UpdateMesh rebuilds the floor, rocky wall border and debris
# (exactly what the UI's Cave Brush does). Params:
#   points:[[x,y]...] (>=1) woxel path; single point = one dab.
#   radius (woxels, default 256 = 1 tile), value/dig (true=dig open, false=fill),
#   ground_color / wall_color (optional tints), texture (optional Caves asset).
# A multi-point path is rasterized as a constant-width ribbon so it digs a smooth
# tunnel (like paint_path, but into the cave bitmap).
func _dig_cave(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var cave = _cave_mesh()
	if cave == null: return _err("cave brush/mesh unavailable")
	if not cave.has_method("get_Bitmap") or not cave.has_method("SetBitmap"):
		return _err("cave mesh missing BitMap API")

	# Optional cave tints / floor texture (apply before the mesh rebuild).
	if req.has("ground_color") and str(req.get("ground_color", "")) != "":
		var gc = _color(req["ground_color"], Color(0.5, 0.5, 0.45))
		if cave.has_method("SetGroundColor"): cave.call("SetGroundColor", gc)
	if req.has("wall_color") and str(req.get("wall_color", "")) != "":
		var wc = _color(req["wall_color"], Color(0.5, 0.5, 0.45))
		if cave.has_method("SetWallColor"): cave.call("SetWallColor", wc)
	if req.has("texture") and str(req.get("texture", "")) != "":
		var tex = _asset_tex("Caves", req["texture"])
		if tex != null and cave.has_method("SetFloorTexture"):
			cave.call("SetFloorTexture", tex)

	# Path -> cell-space points.
	var pts := []
	if req.has("points"):
		for p in req["points"]:
			pts.append(_cave_cell(cave, Vector2(float(p[0]), float(p[1]))))
	else:
		pts.append(_cave_cell(cave, _xy(req, Global.World.WoxelDimensions * 0.5)))
	if pts.empty(): return _err("provide 'points':[[x,y]...] or x/y")

	var value = bool(req.get("value", req.get("dig", true)))
	var cs = cave.call("get_CellSize")
	var rad_cells = max(int(round(float(req.get("radius", 256.0)) / cs)), 1)

	var bm = cave.call("get_Bitmap")
	if bm == null: return _err("cave bitmap is null")
	var size = bm.call("get_size")
	var bw = int(size.x)
	var bh = int(size.y)
	# Rasterize the stroke: dab each point, then thicken the segments between them.
	var n := 0
	for cell in pts:
		n += _cave_stamp(bm, cell, rad_cells, value, bw, bh)
	for i in range(pts.size() - 1):
		_cave_stroke_segment(bm, pts[i], pts[i + 1], rad_cells, value, bw, bh)

	cave.call("SetBitmap", bm)
	if cave.has_method("FinalizeMeshAndBorders"):
		cave.call("FinalizeMeshAndBorders")
	cave.call("UpdateMesh")
	return _ok({
		"dug": value, "cells_painted": n, "radius_cells": rad_cells,
		"points": pts.size(), "bitmap_size": [bw, bh],
	})


# Stamp a filled circle of cells into the BitMap. Returns the count set.
func _cave_stamp(bm, c : Vector2, rad : int, value : bool, bw : int, bh : int) -> int:
	var n := 0
	var x0 = max(int(c.x) - rad, 0)
	var y0 = max(int(c.y) - rad, 0)
	var x1 = min(int(c.x) + rad, bw - 1)
	var y1 = min(int(c.y) + rad, bh - 1)
	for iy in range(y0, y1 + 1):
		for ix in range(x0, x1 + 1):
			if Vector2(ix, iy).distance_to(c) <= rad:
				bm.call("set_bit", Vector2(ix, iy), value)
				n += 1
	return n


# Stamp a thick line of cells between two cell-space points (no gaps between dabs).
func _cave_stroke_segment(bm, a : Vector2, b : Vector2, rad : int, value : bool, bw : int, bh : int) -> void:
	var steps = int(ceil(a.distance_to(b)))
	if steps <= 0:
		return
	for s in range(steps + 1):
		_cave_stamp(bm, a.linear_interpolate(b, float(s) / steps), rad, value, bw, bh)


# Wipe the entire cave layer back to solid rock. Uses the native Clear() then
# rebuilds the mesh; if Clear isn't present, falls back to zeroing the BitMap
# (set every bit false) and pushing it back — both render via UpdateMesh. This is
# a CAVE_CMD, so it's BitMap-snapshotted for undo like dig_cave.
func _clear_caves(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var cave = _cave_mesh()
	if cave == null: return _err("cave brush/mesh unavailable")
	var method = ""
	if cave.has_method("Clear"):
		cave.call("Clear")
		method = "Clear"
	elif cave.has_method("get_Bitmap") and cave.has_method("SetBitmap"):
		var bm = cave.call("get_Bitmap")
		if bm != null:
			var size = bm.call("get_size")
			for iy in range(int(size.y)):
				for ix in range(int(size.x)):
					bm.call("set_bit", Vector2(ix, iy), false)
			cave.call("SetBitmap", bm)
			method = "zero_bitmap"
	else:
		return _err("cave mesh missing Clear/BitMap API")
	if cave.has_method("FinalizeMeshAndBorders"):
		cave.call("FinalizeMeshAndBorders")
	cave.call("UpdateMesh")
	return _ok({ "cleared": true, "method": method })


func _list_elements(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null:
		return _err("no map open")
	var kind = req.get("kind", "objects")
	if not COLLECTIONS.has(kind):
		return _err("unknown kind '%s' (one of: %s)" % [kind, COLLECTIONS.keys()])
	var limit = int(req.get("limit", 200))
	var offset = int(req.get("offset", 0))
	if limit < 1 or limit > 500 or offset < 0:
		return _err("limit must be 1..500 and offset must be nonnegative")
	var out := []
	var total := 0
	for node in _elements(level, kind):
		if total >= offset and out.size() < limit:
			out.append(_describe(node))
		total += 1
	return _ok({ "kind": kind, "offset": offset, "limit": limit, "total": total, "count": out.size(), "elements": out })


# Describe a wall-mounted portal (a door/window living in a wall's Portals
# array). Reports its world `position`, the door's half-width `radius`, and an
# outward `normal` (unit vector pointing OUT of the building) plus `facing` in
# degrees. The normal is `Direction` (the along-wall tangent) rotated 90°,
# oriented to point away from the wall's centroid — so a caller can route a road
# to the door and offset along `normal` to stop at the threshold, with no
# knowledge of how the door was placed (it's pure geometry from the data).
func _describe_wall_portal(portal, wall) -> Dictionary:
	var pos = portal.get("position")
	if pos == null or not (pos is Vector2):
		pos = Vector2()
	var tangent = portal.get("Direction")
	if tangent == null or not (tangent is Vector2) or tangent.length() < 0.001:
		tangent = Vector2(1, 0)
	else:
		tangent = tangent.normalized()
	# Outward normal = tangent rotated 90 degrees, flipped to face away from the
	# wall's centroid (which is inside the enclosed room for a building loop).
	var normal = Vector2(-tangent.y, tangent.x)
	var centroid = _wall_centroid(wall)
	if centroid != null and (pos - centroid).dot(normal) < 0.0:
		normal = -normal
	var d := {
		"id": _id(portal), "kind": "wall_portal", "wall_id": _id(wall),
		"position": _vec(pos), "normal": _vec(normal),
		"facing": rad2deg(normal.angle()),
		"closed": bool(portal.get("Closed")),
	}
	var r = portal.get("Radius")
	if r != null:
		d["radius"] = float(r)
		d["bounds"] = [_vec(pos - Vector2(r, r)), _vec(pos + Vector2(r, r))]
	if portal is Node2D:
		d["layer"] = portal.z_index
	var tex = portal.get("Texture")
	if tex != null and tex is Texture:
		d["asset"] = tex.resource_path
	return d


# Mean of a wall's points — used to orient a portal's normal outward. Returns
# null for a wall with no usable points.
func _wall_centroid(wall):
	var pts = wall.get("Points")
	if pts == null or pts.size() == 0:
		return null
	var sum = Vector2()
	for p in pts:
		sum += p
	return sum / pts.size()


func _get_element(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null:
		return _err("no element with id " + str(req.get("id")))
	return _ok(_describe(node))


func _list_levels() -> Dictionary:
	var out := []
	for i in range(Global.World.levels.size()):
		var lv = Global.World.levels[i]
		out.append({"index": i, "id": lv.ID, "label": lv.Label})
	return _ok({"current_index": Global.World.CurrentLevelId, "current_id": Global.World.GetCurrentLevel().ID, "levels": out})

# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

func _place_object(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var tex = _asset_tex("Objects", req.get("asset", ""))
	if tex == null: return _err("could not load object asset: " + str(req.get("asset")))
	if not _batch_integer(req.get("layer", 0), -1000, 1000):
		return _err("object layer must be an integer in -1000..1000")
	var sorting = int(req.get("sorting", 0))
	var scale_value = float(req.get("scale", 1.0))
	# LoadObject initializes native shader materials, search registration and IDs.
	# SetCustomColor alone cannot initialize a newly created prop's shader.
	# DictionaryEx.Read expects Godot's serialized Vector2 and hexadecimal color.
	var data := {
		"texture": tex.resource_path,
		"position": var2str(_xy(req, Global.World.WoxelDimensions * 0.5)),
		"scale": var2str(Vector2(scale_value, scale_value)),
		"rotation": deg2rad(float(req.get("rotation", 0.0))),
		"layer": int(req.get("layer", 0)),
		"shadow": true,
	}
	if req.has("color"):
		data["custom_color"] = _color(req["color"], Color(1, 1, 1)).to_html(true)
	var prop = level.Objects.LoadObject(data)
	if prop == null: return _err("LoadObject returned null")
	if sorting == 1:
		level.Objects.RemoveFromSearchTable(prop)
		level.Objects.move_child(prop, 0)
		level.Objects.AddToSearchTable(prop, true)
	return _ok({ "id": _id(prop), "position": _vec(prop.position) })


func _draw_wall(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] pairs")
	var tex = _asset_tex("Walls", req.get("asset", ""))
	var wall = level.Walls.AddWall(
		pts, tex, _wall_color(req, tex),
		bool(req.get("loop", false)), bool(req.get("shadow", true)),
		int(req.get("type", 0)), int(req.get("joint", 1)), true)
	if wall == null: return _err("AddWall returned null (bad asset/points?)")
	return _ok({ "id": _id(wall), "point_count": pts.size() })


# Wall tint: use the caller's `color` if given, else the texture's own default
# (WallTool.GetWallColor) so stone/wood walls render with their natural tint
# instead of a bleached white (Color(1,1,1) = no tint = washed-out base).
func _wall_color(req : Dictionary, tex) -> Color:
	if req.has("color") and str(req.get("color", "")) != "":
		return _color(req["color"], Color(1, 1, 1))
	if tex != null and Global.Editor.Tools.has("WallTool"):
		var wt = Global.Editor.Tools["WallTool"]
		if wt.has_method("GetWallColor"):
			var c = wt.GetWallColor(tex)
			if c != null and c is Color:
				return c
	return Color(1, 1, 1)


func _draw_path(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] pairs")
	var tex = _asset_tex("Paths", req.get("asset", ""))
	if tex == null: return _err("could not load path asset: " + str(req.get("asset")))
	var path = level.Pathways.CreatePath(
		tex, int(req.get("layer", 0)), int(req.get("sorting", 0)),
		bool(req.get("fade_in", false)), bool(req.get("fade_out", false)),
		bool(req.get("grow", false)), bool(req.get("shrink", false)))
	path.SetEditPoints(pts)
	if req.has("smoothness"):
		path.Smoothness = float(req["smoothness"])
		path.Smooth()
	if req.has("width"):
		path.SetWidthScale(float(req["width"]))
	path.UpdateGradient()
	path.set_meta("preview", false)
	return _ok({ "id": _id(path), "point_count": pts.size() })


func _add_light(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var light = level.Lights.CreateLight(false)
	light.position = _xy(req, Global.World.WoxelDimensions * 0.5)
	light.color = _color(req.get("color", ""), Color(1, 0.9, 0.7))
	light.energy = float(req.get("energy", 1.0))
	light.texture_scale = float(req.get("range", 1.0))
	light.shadow_enabled = bool(req.get("shadows", true))
	var tex = _asset_tex("Lights", req.get("asset", ""))
	if tex != null:
		light.texture = tex
	light.set_meta("preview", false)
	return _ok({ "id": _id(light), "position": _vec(light.position) })


# Find the wall segment nearest to `pos`. Returns
# { wall, point_index, closest, direction, distance } or null if no walls.
# A wall is a polyline of `Points`; segment i goes Points[i] -> Points[i+1]
# (plus the closing segment when Loop). We pick the segment whose nearest
# point to `pos` is closest overall, and report that segment's unit tangent.
func _nearest_wall_segment(level, pos : Vector2):
	var best = null
	for wall in level.Walls.get_children():
		var pts = wall.get("Points")
		if pts == null or pts.size() < 2:
			continue
		var seg_count = pts.size() - 1
		if wall.get("Loop"):
			seg_count = pts.size()
		for i in range(seg_count):
			var a = pts[i]
			var b = pts[(i + 1) % pts.size()]
			var closest = _closest_point_on_segment(pos, a, b)
			var dist = pos.distance_to(closest)
			if best == null or dist < best.distance:
				var dir = (b - a)
				if dir.length() > 0.001:
					dir = dir.normalized()
				best = {
					"wall": wall, "point_index": i, "closest": closest,
					"direction": dir, "distance": dist,
				}
	return best


func _closest_point_on_segment(p : Vector2, a : Vector2, b : Vector2) -> Vector2:
	var ab = b - a
	var len2 = ab.dot(ab)
	if len2 < 0.0001:
		return a
	var t = clamp((p - a).dot(ab) / len2, 0.0, 1.0)
	return a + ab * t


func _add_portal(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var tex = _asset_tex("Portals", req.get("asset", ""))
	if tex == null: return _err("could not load portal asset: " + str(req.get("asset")))
	var pos = _xy(req, Global.World.WoxelDimensions * 0.5)
	var closed = bool(req.get("closed", false))
	var radius = float(req.get("radius", 64.0))
	# mount: "wall" (default) snaps onto the nearest wall and cuts a gap;
	# "free" forces a freestanding portal. snap_max caps how far (woxels) a
	# wall may be and still capture the portal.
	var mount = str(req.get("mount", "wall"))
	var snap_max = float(req.get("snap_max", 256.0))
	if mount != "free":
		var seg = _nearest_wall_segment(level, pos)
		if seg != null and seg.distance <= snap_max:
			# Mount onto the wall: snap to the segment, face along it, and let
			# the wall remake its lines so the portal cuts a gap.
			var flip = bool(req.get("flip", false))
			var portal = seg.wall.AddPortal(
				tex, closed, seg.closest, seg.direction,
				seg.point_index, radius, flip)
			seg.wall.RemakeLines()
			if portal == null: return _err("Wall.AddPortal returned null")
			return _ok({
				"id": _id(portal), "kind": "wall_portal",
				"position": _vec(seg.closest), "wall_id": _id(seg.wall),
				"snapped": _vec(seg.closest), "snap_distance": seg.distance,
			})
		if mount == "wall" and not req.get("fallback_free", true):
			return _err("no wall within snap_max (%d) of portal position" % int(snap_max))
	# Freestanding fallback (no wall nearby, or mount == "free").
	level.CreateFreestandingPortal(
		tex, pos, closed, radius, deg2rad(float(req.get("rotation", 0.0))))
	# CreateFreestandingPortal returns void; the new portal is the last child.
	var kids = level.Portals.get_children()
	if kids.empty(): return _err("portal was not created")
	return _ok({ "id": _id(kids[kids.size() - 1]), "kind": "portal", "position": _vec(pos) })


# Add a roof. KEY MODEL (learned by probing): Roof.Set(points, width, type) takes
# the roof's RIDGE LINE (the peak), NOT a footprint to trace — it builds a
# complete, self-closing roof that slopes down `width` woxels perpendicular to
# each side of the ridge, with hips/gables off the ridge ends. So:
#   - 2 points = one clean roof (a short ridge -> a near-pyramid hip).
#   - the footprint covered = the ridge bounding box expanded by `width` on all
#     sides. For a building W x H, put the ridge along the LONG axis, centered,
#     and set width = half the SHORT dimension so the eaves reach the walls.
# (Earlier code wrongly treated points as a footprint and "closed" the loop,
# which duplicated a vertex and malformed the seam corner — removed.)
func _add_roof(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var pts = _points(req.get("points", []))
	if pts.size() < 2: return _err("'points' needs >= 2 [x,y] ridge points")
	var tex = _asset_tex("Roofs", req.get("asset", ""))
	if tex == null: return _err("could not load roof asset: " + str(req.get("asset")))
	var roof = level.Roofs.CreateRoof(int(req.get("sorting", 0)))
	roof.Set(pts, float(req.get("width", 256.0)), int(req.get("type", 0)))  # type: 0 gable,1 hip,2 dormer
	roof.SetTileTexture(tex)
	return _ok({ "id": _id(roof), "ridge_points": pts.size() })


# Place a tiled floor/pattern shape (the "Floor" / Pattern Shape Tool in the UI).
# The shape's texture is set on the PatternShapeTool, then DrawRect/DrawPolygon
# rasterizes the shape into the pattern layer. Pass `rect:[x,y,w,h]` OR
# `points:[[x,y]...]`. `category` selects the asset bank ("Patterns",
# "Patterns Colorable", "Materials", "Simple Tiles", "Smart Tiles").
func _place_pattern(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	if not Global.Editor.Tools.has("PatternShapeTool"):
		return _err("PatternShapeTool not available")
	if not _batch_integer(req.get("z", -100), -1000, 1000):
		return _err("pattern layer z must be an integer in -1000..1000")
	var category = str(req.get("category", "Patterns"))
	var tex = _asset_tex(category, req.get("asset", ""))
	if tex == null: return _err("could not load pattern asset: " + str(req.get("asset")))

	var shapes = level.PatternShapes
	var pattern_tool = Global.Editor.Tools["PatternShapeTool"]
	pattern_tool.Texture = tex
	# PatternShapeTool.SetLayer takes a dropdown INDEX, not a layer number.
	# Move the created shape with PatternShape.SetLayer below instead.
	#
	# Color. CRITICAL: PatternShapeTool.Color is PERSISTENT TOOL STATE that leaks
	# across calls — it holds whatever the previous place_pattern set, NOT a
	# per-texture default (unlike walls, which have WallTool.GetWallColor(tex);
	# patterns have no such per-texture lookup). Reading it back as a "default"
	# made every no-color call inherit the last call's tint, and if it was ever
	# left transparent (alpha~0) every subsequent floor rendered INVISIBLE. So we
	# never trust tool.Color: an explicit `color` is used verbatim; with no color
	# we set a deterministic OPAQUE neutral tint so each call is independent and
	# always renders. (Pass an explicit color for an exact look.)
	var color
	var used_default = false
	if req.has("color") and str(req.get("color", "")) != "":
		color = _color(req["color"], DEFAULT_PATTERN_TINT)
	else:
		color = DEFAULT_PATTERN_TINT
		used_default = true
	if color.a < 0.05:  # guard: never paint an invisible floor
		color = Color(color.r, color.g, color.b, 1.0)
	pattern_tool.Color = color  # always set, so we don't inherit/leave leaked state
	var rotation = float(req.get("rotation", 0.0))
	if pattern_tool.get("Rotation") != null:
		pattern_tool.Rotation.value = rotation

	var before := shapes.GetShapes().size()
	var kind : String
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		shapes.DrawRect(Rect2(float(r[0]), float(r[1]), float(r[2]), float(r[3])), false)
		kind = "rect"
	elif req.has("points"):
		var pts = _points(req["points"])
		if pts.size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs for a polygon")
		shapes.DrawPolygon(pts, false)
		kind = "polygon"
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	# Apply the resolved texture/tint directly. Native SetOptions uses radians;
	# the MCP API and PatternShapeTool rotation control use degrees.
	#
	# Native Save() serializes GetLayer() (the parent layer), not shape.z_index.
	# SetLayer uses GetOrMakeLayer and preserves the actual editable layer.
	var all = shapes.GetShapes()
	var result := { "shape": kind, "category": category, "shape_count": all.size() }
	if color is Color:
		result["color"] = "#" + color.to_html(true)
	if used_default:
		# Signal we applied the neutral default (no per-texture tint exists for
		# patterns; pass an explicit `color` for an exact look).
		result["used_default_tint"] = true
	if all.size() > before and all.size() > 0:
		var shape = all[all.size() - 1]
		if shape.has_method("SetOptions"):
			shape.SetOptions(tex, color, deg2rad(rotation))
		shape.SetLayer(int(req.get("z", -100)))
		shape.z_as_relative = true
		shape.z_index = 0
		result["id"] = _id(shape)
		result["z_index"] = int(shape.GetLayer())
		result["layer"] = int(shape.GetLayer())
	return _ok(result)


# Build a room in one call: a looped wall AND a floor along the SAME boundary
# path, so the floor meets the wall exactly (the wall covers the floor's outer
# edge) — the way the UI's combined wall+floor trace works. Pass `rect:[x,y,w,h]`
# or `points:[[x,y]...]`. Floor is a pattern by default (`floor:"pattern"`,
# floor_asset + floor_category) or terrain (`floor:"terrain"`, floor_asset +
# floor_slot). Pass `floor:"none"` for walls only. Reuses _draw_wall /
# _place_pattern / _fill_region so behavior matches those tools exactly.
func _build_room(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")

	# Normalize the boundary to a list of [x,y] points (rect -> 4 corners).
	var pts_raw := []
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var x = float(r[0]); var y = float(r[1]); var w = float(r[2]); var h = float(r[3])
		pts_raw = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
	elif req.has("points"):
		if typeof(req["points"]) != TYPE_ARRAY or req["points"].size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs")
		pts_raw = req["points"]
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	var result := {}

	# 1) Wall loop along the boundary.
	var wall_req := {
		"points": pts_raw, "loop": true,
		"asset": req.get("wall_asset", ""),
		"type": req.get("wall_type", 0), "joint": req.get("wall_joint", 1),
		"shadow": req.get("wall_shadow", true),
	}
	var wall_res = _draw_wall(wall_req)
	if not wall_res.get("ok", false):
		return wall_res
	result["wall_id"] = wall_res["result"].get("id")

	# 2) Floor along the SAME boundary (no inset — the wall covers the seam).
	var floor_kind = str(req.get("floor", "pattern"))
	if floor_kind == "pattern":
		var fr := {
			"points": pts_raw,
			"asset": req.get("floor_asset", ""),
			"category": req.get("floor_category", "Simple Tiles"),
		}
		if req.has("floor_color"): fr["color"] = req["floor_color"]
		if req.has("floor_z"): fr["z"] = req["floor_z"]
		var fres = _place_pattern(fr)
		if fres.get("ok", false):
			result["floor_id"] = fres["result"].get("id")
		else:
			result["floor_error"] = fres.get("error")
	elif floor_kind == "terrain":
		var tr := {
			"points": pts_raw, "slot": int(req.get("floor_slot", 1)),
		}
		if req.has("floor_asset") and str(req.get("floor_asset", "")) != "":
			tr["asset"] = req["floor_asset"]
		var tres = _fill_region(tr)
		if tres.get("ok", false):
			result["floor_pixels"] = tres["result"].get("pixels")
		else:
			result["floor_error"] = tres.get("error")
	# floor_kind == "none" -> walls only

	result["points"] = pts_raw
	return _ok(result)


# A Dungeondraft Text extends Godot LineEdit: the string is the inherited
# `.text`, position is `rect_position`, and size/color must be applied through
# the TextTool (see below) because UpdateText repaints from the tool's settings.
func _add_text(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var text = level.Texts.CreateText()
	# A Text extends LineEdit (a Control): place it via rect_position, not the
	# Node2D `.position` (which silently does nothing on a Control).
	text.rect_position = _xy(req, Global.World.WoxelDimensions * 0.5)
	text.text = str(req.get("text", ""))
	# Font/size/color: TextTool.UpdateText() repaints the focused Text from the
	# TOOL's settings (FontSize/FontColor), overwriting anything set directly on
	# the node. So drive it through the tool: stash the tool's values, set ours,
	# repaint, then restore the tool so the user's UI state is unchanged.
	# A fresh Text reports fontSize 0 until repainted, so default to 32 (DD's
	# standard) rather than the node's pre-paint value when no size is given.
	var size = int(req.get("size", 32))
	if size <= 0:
		size = 32
	var col = _color(req.get("color", ""), Color(0, 0, 0, 1))
	var font_name = str(req.get("font", text.fontName))
	if req.has("font"):
		text.SetFont(font_name, size)  # font name has no tool-member path
	if Global.Editor.Tools.has("TextTool"):
		var tt = Global.Editor.Tools["TextTool"]
		var saved_size = tt.FontSize
		var saved_color = tt.FontColor
		tt.FontSize = size
		tt.FontColor = col
		tt.focus = text
		tt.UpdateText(text)
		tt.FontSize = saved_size
		tt.FontColor = saved_color
	else:
		# No tool available: best-effort direct set.
		text.fontSize = size
		text.fontColor = col
		text.SetFont(font_name, size)
		text.SetFontColor(col)
	return _ok({ "id": _id(text), "size": text.fontSize, "color": "#" + text.fontColor.to_html(false) })


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------

func _set_terrain_slot(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var tex = _asset_tex("Terrain", req.get("asset", ""))
	if tex == null: return _err("could not load terrain asset: " + str(req.get("asset")))
	var slot = int(req.get("slot", 0))
	level.Terrain.SetTexture(tex, slot)
	level.Terrain.UpdateSplat()
	return _ok({ "slot": slot })


func _fill_terrain(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)
	level.Terrain.Fill(slot)
	level.Terrain.UpdateSplat()
	return _ok({ "filled_slot": slot })


# Paint a soft circular brush of a terrain slot at a woxel position. Like
# fill_region, this edits the splat weight image directly (Terrain.Paint is a
# no-op from a mod context). The brush has a smooth radial falloff so strokes
# blend; `rate` scales the peak strength at the center.
func _paint_terrain(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var radius = float(req.get("radius", 64.0))
	var rate = clamp(float(req.get("rate", 1.0)), 0.0, 1.0)
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)
	var world = _xy(req, Global.World.WoxelDimensions * 0.5)
	# Convert the brush center and radius into texture space (radius scales by
	# the woxel->texture ratio along x).
	var center = level.Terrain.WorldToTexture(world)
	var tscale = float(level.Terrain.width) / max(Global.World.WoxelDimensions.x, 1.0)
	var trad = max(radius * tscale, 0.5)

	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var ch = sp.ch
	var iw = img.get_width()
	var ih = img.get_height()
	var x0 = int(floor(center.x - trad))
	var y0 = int(floor(center.y - trad))
	var x1 = int(ceil(center.x + trad))
	var y1 = int(ceil(center.y + trad))
	var painted := 0
	img.lock()
	for iy in range(max(y0, 0), min(y1 + 1, ih)):
		for ix in range(max(x0, 0), min(x1 + 1, iw)):
			var d = Vector2(ix + 0.5, iy + 0.5).distance_to(center)
			if d > trad:
				continue
			# Smooth falloff: full strength in the inner half, easing to 0 at the rim.
			var falloff = clamp(1.0 - (d / trad), 0.0, 1.0)
			falloff = falloff * falloff * (3.0 - 2.0 * falloff)  # smoothstep
			var w = rate * falloff
			if w <= 0.0:
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), ch, w))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)
	return _ok({ "painted_slot": slot, "pixels": painted })


# Paint a continuous terrain stroke along a polyline (a road/trail) in one call.
# Unlike stamping many `paint_terrain` dabs (whose overlaps double-paint and whose
# spacing the caller has to eyeball), this rasterizes a uniform ribbon: for each
# pixel near the line it measures the distance to the NEAREST segment and applies
# the soft falloff once, so the whole route has constant width and clean edges.
# `points` is a woxel polyline (>= 2 [x,y] pairs); `radius` is the half-width.
func _paint_path(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var radius = float(req.get("radius", 96.0))
	var rate = clamp(float(req.get("rate", 1.0)), 0.0, 1.0)
	if not req.has("points"):
		return _err("provide 'points':[[x,y]...] (>= 2 points)")
	var pts = req["points"]
	if typeof(pts) != TYPE_ARRAY or pts.size() < 2:
		return _err("'points' needs >= 2 [x,y] pairs for a path")
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)

	# Map the polyline into texture space; radius scales by the woxel->texture
	# ratio (same conversion paint_terrain uses for a single dab).
	var tscale = float(level.Terrain.width) / max(Global.World.WoxelDimensions.x, 1.0)
	var trad = max(radius * tscale, 0.5)
	var tpts := []
	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	for p in pts:
		var tp = level.Terrain.WorldToTexture(Vector2(float(p[0]), float(p[1])))
		tpts.append(tp)
		mn.x = min(mn.x, tp.x); mn.y = min(mn.y, tp.y)
		mx.x = max(mx.x, tp.x); mx.y = max(mx.y, tp.y)

	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var ch = sp.ch
	var iw = img.get_width()
	var ih = img.get_height()
	# Bounding box of the whole stroke, padded by the brush radius.
	var x0 = max(int(floor(mn.x - trad)), 0)
	var y0 = max(int(floor(mn.y - trad)), 0)
	var x1 = min(int(ceil(mx.x + trad)), iw - 1)
	var y1 = min(int(ceil(mx.y + trad)), ih - 1)
	var painted := 0
	img.lock()
	for iy in range(y0, y1 + 1):
		for ix in range(x0, x1 + 1):
			var pix = Vector2(ix + 0.5, iy + 0.5)
			# Distance to the closest segment of the polyline.
			var d = INF
			for i in range(tpts.size() - 1):
				var sd = _dist_point_segment(pix, tpts[i], tpts[i + 1])
				if sd < d:
					d = sd
				if d <= 0.0:
					break
			if d > trad:
				continue
			# Same smoothstep falloff as paint_terrain, applied once per pixel.
			var falloff = clamp(1.0 - (d / trad), 0.0, 1.0)
			falloff = falloff * falloff * (3.0 - 2.0 * falloff)
			var w = rate * falloff
			if w <= 0.0:
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), ch, w))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)
	return _ok({ "painted_slot": slot, "segments": tpts.size() - 1, "pixels": painted })


# Shortest distance from point p to segment a-b (all in texture space).
func _dist_point_segment(p : Vector2, a : Vector2, b : Vector2) -> float:
	var ab = b - a
	var len2 = ab.x * ab.x + ab.y * ab.y
	if len2 <= 0.0000001:
		return p.distance_to(a)
	var t = clamp((p - a).dot(ab) / len2, 0.0, 1.0)
	return p.distance_to(a + ab * t)


# Fill a region (rectangle or polygon) with a terrain slot, in woxel coords.
# Unlike fill_terrain (whole level), this paints only inside the shape, so you
# can floor a single room. Pass `rect:[x,y,w,h]` OR `points:[[x,y]...]` (a
# polygon, >= 3 points). The shape is mapped to texture space and rasterized
# directly into the splat weight image (see below), not via Terrain.Paint.
func _fill_region(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var slot = int(req.get("slot", 0))
	var rate = float(req.get("rate", 1.0))
	if req.has("asset"):
		var tex = _asset_tex("Terrain", req["asset"])
		if tex == null: return _err("could not load terrain asset: " + str(req["asset"]))
		level.Terrain.SetTexture(tex, slot)

	# Gather the shape's world-space polygon (rect -> 4 corners).
	var poly := []
	if req.has("rect"):
		var r = req["rect"]
		if typeof(r) != TYPE_ARRAY or r.size() < 4:
			return _err("'rect' must be [x, y, w, h]")
		var x = float(r[0]); var y = float(r[1]); var w = float(r[2]); var h = float(r[3])
		poly = [Vector2(x, y), Vector2(x + w, y), Vector2(x + w, y + h), Vector2(x, y + h)]
	elif req.has("points"):
		for p in req["points"]:
			poly.append(Vector2(float(p[0]), float(p[1])))
		if poly.size() < 3:
			return _err("'points' needs >= 3 [x,y] pairs for a polygon")
	else:
		return _err("provide 'rect':[x,y,w,h] or 'points':[[x,y]...]")

	# Map the polygon into texture space and find its pixel bounding box.
	var tpoly := []
	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	for wp in poly:
		var tp = level.Terrain.WorldToTexture(wp)
		tpoly.append(tp)
		mn.x = min(mn.x, tp.x); mn.y = min(mn.y, tp.y)
		mx.x = max(mx.x, tp.x); mx.y = max(mx.y, tp.y)
	var origin = Vector2(floor(mn.x), floor(mn.y))
	var bw = int(ceil(mx.x - origin.x))
	var bh = int(ceil(mx.y - origin.y))
	if bw < 1 or bh < 1:
		return _err("region is too small in texture space")

	# Edit the splat weight image directly (Terrain.Paint is a no-op from a mod
	# context). For each pixel inside the polygon, drive the target slot's
	# channel toward 1 by `rate`; _open/_close_splat handle clone + restore.
	var local := []
	for tp in tpoly:
		local.append(tp - origin)
	rate = clamp(rate, 0.0, 1.0)
	var sp = _open_splat(level, slot)
	if sp == null: return _err("could not read splat image for slot " + str(slot))
	var img = sp.img
	var iw = img.get_width()
	var ih = img.get_height()
	var painted := 0
	img.lock()
	for py in range(bh):
		var iy = int(origin.y) + py
		if iy < 0 or iy >= ih:
			continue
		for px in range(bw):
			var ix = int(origin.x) + px
			if ix < 0 or ix >= iw:
				continue
			if not _point_in_poly(Vector2(px + 0.5, py + 0.5), local):
				continue
			img.set_pixel(ix, iy, _splat_set_channel(img.get_pixel(ix, iy), sp.ch, rate))
			painted += 1
	img.unlock()
	_close_splat(level, sp.which, img)

	return _ok({
		"filled_slot": slot, "shape": ("rect" if req.has("rect") else "polygon"),
		"texture_bbox": [_vec(origin), [origin.x + bw, origin.y + bh]],
		"pixels": painted,
	})


# Clone the splat weight image holding `slot` for direct editing. Returns
# { img, ch, which } where ch is the RGBA channel (0..3) for that slot and
# which is 0 (slots 0-3 -> splatImage) or 1 (slots 4-7 -> splatImage2), or null
# if the image isn't available. Pair with _close_splat to push edits back.
func _open_splat(level, slot : int):
	var which = 0 if slot < 4 else 1
	var img = level.Terrain.CloneSplatImage() if which == 0 else level.Terrain.CloneSplatImage2()
	if img == null:
		return null
	return { "img": img, "ch": slot % 4, "which": which }


func _close_splat(level, which : int, img) -> void:
	if which == 0:
		level.Terrain.RestoreSplat(img)
	else:
		level.Terrain.RestoreSplat2(img)
	level.Terrain.UpdateSplat()


# Push channel `ch` (0=R,1=G,2=B,3=A) of an RGBA splat weight toward 1 by `rate`,
# scaling the remaining channels down so the four weights still sum to ~1.
func _splat_set_channel(c : Color, ch : int, rate : float) -> Color:
	var w = [c.r, c.g, c.b, c.a]
	var target = w[ch] + (1.0 - w[ch]) * rate
	var rest = 1.0 - target
	var others = (w[0] + w[1] + w[2] + w[3]) - w[ch]
	for i in range(4):
		if i == ch:
			w[i] = target
		elif others > 0.0001:
			w[i] = w[i] / others * rest
		else:
			w[i] = 0.0
	return Color(w[0], w[1], w[2], w[3])


# Even-odd point-in-polygon test (ray cast). `poly` is an array of Vector2.
func _point_in_poly(pt : Vector2, poly : Array) -> bool:
	var inside = false
	var n = poly.size()
	var j = n - 1
	for i in range(n):
		var a = poly[i]
		var b = poly[j]
		if ((a.y > pt.y) != (b.y > pt.y)) and \
				(pt.x < (b.x - a.x) * (pt.y - a.y) / (b.y - a.y) + a.x):
			inside = not inside
		j = i
	return inside


# ---------------------------------------------------------------------------
# Modify / delete
# ---------------------------------------------------------------------------

func _move_element(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))
	if _is_text(node):
		node.rect_position = _xy(req, node.rect_position)
		return _ok({ "id": req.get("id"), "position": _vec(node.rect_position) })
	if not (node is Node2D): return _err("element is not movable")
	node.position = _xy(req, node.position)
	return _ok({ "id": req.get("id"), "position": _vec(node.position) })


func _modify_object(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))
	# A native tint setter only updates an existing shader; reject before any edit.
	if req.has("color") and (not node.has_method("HasCustomColor") or not node.HasCustomColor()):
		return _err("object tint is not initialized; create the object with an explicit color")
	if req.has("layer"):
		if node.get_parent() != Global.World.GetCurrentLevel().Objects or not _batch_integer(req["layer"], -1000, 1000):
			return _err("layer requires a current-level object and an integer in -1000..1000")
	if req.has("asset"):
		if node.get_parent() != Global.World.GetCurrentLevel().Objects:
			return _err("retexture requires an object")
		var tex = _asset_tex("Objects", req["asset"])
		if tex == null: return _err("object asset cannot be loaded")
		node.SetTexture(tex)
	if req.has("scale"):
		var s = float(req["scale"]); node.scale = Vector2(s, s)
	if req.has("rotation"):
		node.rotation = deg2rad(float(req["rotation"]))
	if req.has("color") and node.has_method("SetCustomColor"):
		node.SetCustomColor(_color(req["color"], Color(1, 1, 1)))
	if req.has("shadow"):
		node.set("HasShadow", bool(req["shadow"]))
	if req.has("layer"):
		_set_object_layer(node, int(req["layer"]))
	return _ok(_describe(node))


func _duplicate_object(req : Dictionary) -> Dictionary:
	var level = Global.World.GetCurrentLevel()
	if level == null: return _err("no map open")
	var src = _resolve(req)
	if src == null: return _err("no element with id " + str(req.get("id")))
	if src.get_parent() != level.Objects: return _err("duplicate requires a current-level object")
	if src.get("Texture") == null: return _err("element has no Texture to duplicate")
	# Native copy serialization preserves tint/shader, shadow, mirror and layer.
	# copy=true omits node_id so the duplicate receives its own identity.
	var data = src.Save(true)
	data["position"] = var2str(src.position + Vector2(float(req.get("dx", 64.0)), float(req.get("dy", 0.0))))
	var prop = level.Objects.LoadObject(data)
	if prop == null: return _err("LoadObject returned null")
	return _ok({ "id": _id(prop), "position": _vec(prop.position) })


func _delete_element(req : Dictionary) -> Dictionary:
	var ident = req.get("id")
	if ident == null: return _err("missing 'id'")
	var node = Global.World.GetNodeByID(int(ident))
	if node != null:
		_deselect_node(node)
	var ok = Global.World.DeleteNodeByID(int(ident))
	return _ok({ "deleted": ok, "id": ident })


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

func _add_level(req : Dictionary) -> Dictionary:
	var lv = Global.World.CreateLevel(str(req.get("label", "Level")))
	Global.Editor.UpdateLevelOptions()
	# CreateLevel inserts at index zero and keeps the previous floor active.
	return _ok({"index": Global.World.levels.find(lv), "id": lv.ID, "label": lv.Label})


func _set_level(req : Dictionary) -> Dictionary:
	if not req.has("index") or not typeof(req["index"]) in [TYPE_INT, TYPE_REAL] or float(req["index"]) != floor(float(req["index"])):
		return _err("index must be an integer")
	var idx = int(req["index"])
	if idx < 0 or idx >= Global.World.levels.size():
		return _err("level index out of range: " + str(idx))
	if idx != Global.World.CurrentLevelId:
		# C# optional arguments must be supplied explicitly through GDScript.
		Global.World.SetLevel(idx, false)
	if Global.World.CurrentLevelId != idx:
		return _err("native editor did not switch to the requested floor")
	Global.Editor.SetLevelOptionsByID(Global.World.GetCurrentLevel().ID)
	return _ok({"current_index": idx, "current_id": Global.World.GetCurrentLevel().ID})

# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

# Grab the current window (what's on screen) to a PNG. Synchronous: the texture
# holds the last drawn frame, so no yield is needed inside update().
func _screenshot(req : Dictionary) -> Dictionary:
	var path = str(req.get("path", ""))
	if path == "": return _err("missing 'path'")
	var img = Global.World.get_viewport().get_texture().get_data()
	if img == null: return _err("viewport capture returned null")
	img.flip_y()  # viewport textures come back vertically flipped
	var err = img.save_png(path)
	if err != OK: return _err("save_png failed (err %d): %s" % [err, path])
	return _ok({ "path": path, "width": img.get_width(), "height": img.get_height() })


# Render the whole map (no UI) to a clean PNG. Asynchronous: Exporter.Start runs
# on a separate thread, so the caller (MCP server) polls the path for the file.
func _export_map(req : Dictionary) -> Dictionary:
	var path = str(req.get("path", ""))
	var ppi = req.get("ppi", 40)
	if not path.is_abs_path(): return _err("absolute export path required")
	if not _batch_integer(ppi, 8, 256): return _err("ppi must be an integer in 8..256")
	var pixels = Global.World.WoxelDimensions / 256.0 * ppi
	if pixels.x * pixels.y > 16777216 or max(pixels.x, pixels.y) > 8192:
		return _err("export exceeds 16 megapixels or 8192 pixels per side; reduce ppi")
	_refresh_export()
	if bool(_master().get("IsExporting")) or not _export_state.empty():
		return _err("export already active")
	if req.has("grid") and typeof(req["grid"]) != TYPE_BOOL: return _err("grid must be boolean")
	if req.has("lighting") and typeof(req["lighting"]) != TYPE_BOOL: return _err("lighting must be boolean")
	var format = req.get("format", "png")
	if not format in ["png", "universalvtt"]: return _err("format must be png or universalvtt")
	_export_state = {"grid": Global.Editor.GridToggle.pressed, "lighting": Global.Editor.LightingToggle.pressed}
	if req.has("grid"):
		Global.Editor.ToggleGrid(req["grid"])
	# Export only the active native floor, including PNG previews of multilevel maps.
	Global.World.SetSourceLevel(Global.World.CurrentLevelId)
	_export_state["restore_levels"] = true
	if req.has("lighting"):
		Global.Editor.ToggleLighting(req["lighting"])
	Global.Exporter.Start(3 if format == "universalvtt" else 0, int(ppi), path)
	return _ok({"path": path, "ppi": ppi, "pixels": _vec(pixels), "async": true})


func _refresh_export():
	if not _export_state.empty() and not bool(_master().get("IsExporting")):
		Global.Editor.ToggleGrid(_export_state["grid"])
		if _export_state.get("restore_levels", false):
			# ToggleLighting requires SourceLevel; restore it before clearing export levels.
			Global.Editor.ToggleLighting(_export_state["lighting"])
			Global.World.RestoreLevelsPostExport()
		_export_state = {}


func _surface_state() -> Dictionary:
	var terrain = Global.World.GetCurrentLevel().Terrain
	var context = HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(terrain.CloneSplatImage().get_data())
	if terrain.ExpandedSlots:
		context.update(terrain.CloneSplatImage2().get_data())
	var paths := []
	for i in range(terrain.textures.size()):
		var texture = terrain.GetTexture(i)
		paths.append(texture.resource_path if texture != null else "")
	context.update(JSON.print(paths).to_utf8())
	return _ok({"terrain_sha256": context.finish().hex_encode(), "textures": paths, "level_id": Global.World.GetCurrentLevel().ID, "terrain_settings": _terrain_settings_data()})


func _delete_object(req : Dictionary) -> Dictionary:
	var node = _resolve(req)
	if node == null or node.get_parent() != Global.World.GetCurrentLevel().Objects:
		return _err("delete_object requires an existing object on the current level")
	_deselect_node(node)
	_detach_node(node, int(req["id"]))
	node.queue_free()
	return _ok({"deleted": true, "id": int(req["id"])})


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
#
# The editor camera is a Camera2D at Global.Camera. Its world center is the
# inherited `global_position`; `zoom` is a Vector2 where LARGER = zoomed OUT
# (a Camera2D scales the view by `zoom`, so zoom 0.5 shows half as much = 2x
# magnification). We expose zoom as a single float = zoom.x and pan by setting
# global_position directly (unambiguous), then nudge DD's zoom dropdown to
# match via SetZoomOptionByRaw so the bottom bar stays in sync.

func _camera():
	return Global.get("Camera")


func _viewport_size() -> Vector2:
	return Global.World.get_viewport().get_visible_rect().size


func _apply_zoom(cam, z : float) -> void:
	z = max(0.01, z)
	cam.zoom = Vector2(z, z)
	# Keep DD's bottom-bar zoom dropdown in sync with the raw zoom value.
	if Global.Editor.has_method("SetZoomOptionByRaw"):
		Global.Editor.SetZoomOptionByRaw(z)


func _camera_state(cam) -> Dictionary:
	return {
		"position": _vec(cam.global_position),
		"zoom": cam.zoom.x,
		"viewport_size": _vec(_viewport_size()),
	}


func _get_camera() -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	return _ok(_camera_state(cam))


func _set_camera(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	if req.has("x") or req.has("y"):
		cam.global_position = _xy(req, cam.global_position)
	if req.has("zoom"):
		_apply_zoom(cam, float(req["zoom"]))
	return _ok(_camera_state(cam))


# Center the camera on a single element (any kind, incl. text). Optional zoom.
func _focus_element(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	var node = _resolve(req)
	if node == null: return _err("no element with id " + str(req.get("id")))
	var pos = _element_position(node)
	if pos == null: return _err("element has no position to focus")
	cam.global_position = pos
	if req.has("zoom"):
		_apply_zoom(cam, float(req["zoom"]))
	return _ok({ "id": req.get("id"), "focused": _vec(pos), "camera": _camera_state(cam) })


# Frame a set of elements: center on the UNION of their world-space bounding
# rects and zoom so it fits the viewport with `pad` (fraction of extra margin,
# default 0.15). Ids that don't resolve or lack bounds are skipped and reported
# in `missing`. Using real rects (not anchor points) keeps wall loops and large
# props correctly centered.
func _fit_elements(req : Dictionary) -> Dictionary:
	var cam = _camera()
	if cam == null: return _err("camera not available")
	var ids = req.get("ids", [])
	var mn = Vector2(INF, INF)
	var mx = Vector2(-INF, -INF)
	var used := 0
	var missing := []
	for ident in ids:
		var node = Global.World.GetNodeByID(int(ident))
		var rect = null
		if node != null:
			rect = _element_rect(node)
		if rect == null:
			missing.append(ident)
			continue
		mn.x = min(mn.x, rect.position.x); mn.y = min(mn.y, rect.position.y)
		mx.x = max(mx.x, rect.end.x); mx.y = max(mx.y, rect.end.y)
		used += 1
	if used == 0:
		return _err("no elements with bounds to fit")
	var center = (mn + mx) * 0.5
	cam.global_position = center
	# Zoom so the box fits: zoom (Camera2D) = world_span / viewport_span.
	var pad = 1.0 + float(req.get("pad", 0.15))
	var raw = mx - mn
	var vp = _viewport_size()
	var z
	if raw.length() < 1.0:
		# Degenerate box (one point, no derivable bounds): use a sane close zoom
		# instead of slamming to the minimum and burying the camera in a pixel.
		z = 1.0
	else:
		var span = raw * pad
		z = max(span.x / max(vp.x, 1.0), span.y / max(vp.y, 1.0))
	_apply_zoom(cam, z)
	return _ok({
		"fit": used, "missing": missing,
		"center": _vec(center), "bounds": [_vec(mn), _vec(mx)],
		"camera": _camera_state(cam),
	})


# A representative world point for any element kind: the center of its bounding
# rect (so walls/large props focus on their middle, not their anchor).
func _element_position(node):
	var rect = _element_rect(node)
	if rect != null:
		return rect.position + rect.size * 0.5
	return null


# A world-space Rect2 enclosing an element's visual extent, or null if none can
# be determined. Prefers the engine's own bounds (GlobalRect on walls/paths,
# get_global_rect on the LineEdit-based Text), then a prop's Rect, then a wall/
# path's Points, finally a zero-size rect at the node position.
func _element_rect(node):
	if _is_text(node):
		return node.get_global_rect()  # Control: world-space rect
	# Portal.Rect is local to its sprite; transform its visual rect to world space.
	if node.get("IsFreestanding") != null:
		var portal_sprite = node.get("Sprite")
		if portal_sprite != null and portal_sprite.has_method("get_rect"):
			return portal_sprite.get_global_transform().xform(portal_sprite.get_rect())
	if node is Light2D and node.texture != null:
		var light_size = node.texture.get_size() * node.texture_scale
		return node.get_global_transform().xform(Rect2(node.offset - light_size * 0.5, light_size))
	var grect = node.get("GlobalRect")
	if grect != null and grect is Rect2 and grect.size.length() > 0.0:
		return grect
	var prect = node.get("Rect")
	if prect != null and prect is Rect2 and prect.size.length() > 0.0:
		return prect
	# A prop's Rect can be empty until DD computes it; derive bounds from the
	# Sprite's texture size * node scale, centered on the node position.
	if node is Node2D:
		var spr = node.get("Sprite")
		if spr != null and spr.has_method("get_texture") and spr.get_texture() != null:
			var tsize = spr.get_texture().get_size() * node.scale
			if tsize.length() > 0.0:
				return Rect2(node.position - tsize * 0.5, tsize)
	var pts = node.get("Points")
	if pts != null and pts is PoolVector2Array and pts.size() > 0:
		var mn = Vector2(INF, INF)
		var mx = Vector2(-INF, -INF)
		for p in pts:
			mn.x = min(mn.x, p.x); mn.y = min(mn.y, p.y)
			mx.x = max(mx.x, p.x); mx.y = max(mx.y, p.y)
		return Rect2(mn, mx - mn)
	if node is Node2D:
		return Rect2(node.position, Vector2())
	return null


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

func _select_elements(req : Dictionary) -> Dictionary:
	if not Global.Editor.Tools.has("SelectTool"):
		return _err("SelectTool unavailable")
	var nodes := []
	for ident in req.get("ids", []):
		var node = Global.World.GetNodeByID(int(ident))
		if node != null and not node.is_queued_for_deletion():
			nodes.append(node)
	if nodes.empty():
		_clear_selection()
		return _ok({ "selected": 0 })
	# EnableTransformBox requires widgets created by SelectTool.Enable().
	# Quickswitch runs the editor's complete, documented activation lifecycle.
	if not Global.Editor.IsToolActive("SelectTool"):
		Global.Editor.Toolset.Quickswitch("SelectTool")
	if not Global.Editor.IsToolActive("SelectTool"):
		return _err("could not activate SelectTool")
	var selection_tool = Global.Editor.Tools["SelectTool"]
	selection_tool.ClearTransformSelection()
	for node in nodes:
		selection_tool.SelectThing(node, true)
	selection_tool.EnableTransformBox(true)
	return _ok({ "selected": nodes.size() })


func _clear_selection() -> Dictionary:
	if not Global.Editor.Tools.has("SelectTool"):
		return _err("SelectTool unavailable")
	var selection_tool = Global.Editor.Tools["SelectTool"]
	if Global.Editor.IsToolActive("SelectTool"):
		selection_tool.ClearTransformSelection()
	else:
		selection_tool.DeselectAll()
	return _ok({ "cleared": true })


func _deselect_node(node):
	if not Global.Editor.Tools.has("SelectTool"):
		return
	var selection_tool = Global.Editor.Tools["SelectTool"]
	var selected = selection_tool.get("Selected")
	if selected == null or not node in selected:
		return
	selection_tool.SelectThing(node, false)
	if Global.Editor.IsToolActive("SelectTool"):
		selection_tool.EnableTransformBox(selection_tool.get("Selected").size() > 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

func _elements(level, kind : String) -> Array:
	# PatternShapes children are layer containers, not selectable shapes.
	if kind == "patterns":
		return level.PatternShapes.GetShapes()
	var nodes := []
	# Mounted portals live under walls; free portals live in level.Portals.
	if kind == "portals":
		for wall in level.Walls.get_children():
			var portals = wall.get("Portals")
			if portals != null:
				for portal in portals:
					nodes.append(portal)
	for node in level.get(COLLECTIONS[kind]).get_children():
		nodes.append(node)
	return nodes


# Stable id for a node: reuse its node_id meta, else allocate+register one.
# Returns -1 if the node type can't be registered (e.g. Text on some versions).
func _id(node) -> int:
	if node.has_meta("node_id"):
		return int(node.get_meta("node_id"))
	var nid = Global.World.AssignNodeID(node)
	if nid != null:
		return int(nid)
	if node.has_meta("node_id"):
		return int(node.get_meta("node_id"))
	return -1


func _resolve(req : Dictionary):
	if not req.has("id"):
		return null
	return Global.World.GetNodeByID(int(req["id"]))


# A DD Text node extends LineEdit (a Control), so GetSelectableType doesn't
# classify it and it has no Node2D `.position` — special-case it up front.
func _is_text(node) -> bool:
	return (node is Control) and node.has_method("SetFontSize")


func _describe(node) -> Dictionary:
	# Both portal types carry WallID. Only mounted portals reference a wall.
	var wall_id = node.get("WallID")
	if wall_id != null and int(wall_id) >= 0 and not bool(node.get("IsFreestanding")):
		var wall = Global.World.GetNodeByID(int(wall_id))
		if wall != null:
			return _describe_wall_portal(node, wall)
	if _is_text(node):
		# DD Text extends LineEdit (Control): position is rect_position, the
		# string is the inherited `.text`, and size/color are the `fontSize` /
		# `fontColor` members. LineEdit has no rotation, so none is reported.
		var td := {
			"id": _id(node), "kind": "text",
			"position": _vec(node.rect_position),
			"text": node.text,
		}
		var fsize = node.get("fontSize")
		if fsize != null:
			td["size"] = int(fsize)
		var fcolor = node.get("fontColor")
		if fcolor != null and fcolor is Color:
			td["color"] = "#" + fcolor.to_html(false)
		var fname = node.get("fontName")
		if fname != null and str(fname) != "":
			td["font"] = str(fname)
		var text_rect = _element_rect(node)
		if text_rect != null:
			td["bounds"] = [_vec(text_rect.position), _vec(text_rect.end)]
		return td
	var stool = Global.Editor.Tools["SelectTool"]
	var t = stool.GetSelectableType(node)
	var d := { "id": _id(node), "kind": KIND_NAMES.get(t, "unknown") }
	if d["kind"] == "portal":
		d["closed"] = bool(node.get("Closed"))
	if node is Node2D:
		d["position"] = _vec(node.position)
		d["rotation"] = rad2deg(node.rotation)
		d["scale"] = node.scale.x
		d["layer"] = int(node.call("GetLayer")) if node.has_method("GetLayer") else node.z_index
	var rect = _element_rect(node)
	if rect != null:
		d["bounds"] = [_vec(rect.position), _vec(rect.end)]
	var pts = _element_points(node)
	if not pts.empty():
		d["points"] = pts
	var tex_path = _texture_path(node, t)
	if tex_path != "":
		d["asset"] = tex_path
	return d


func _element_points(node) -> Array:
	var pts = null
	for property_name in ["GlobalEditPoints", "GlobalPolygon", "Points", "points"]:
		pts = node.get(property_name)
		if pts != null and (typeof(pts) == TYPE_ARRAY or typeof(pts) == TYPE_VECTOR2_ARRAY) and pts.size() > 0:
			break
	var out := []
	if pts != null and (typeof(pts) == TYPE_ARRAY or typeof(pts) == TYPE_VECTOR2_ARRAY):
		for p in pts:
			if p is Vector2:
				out.append(_vec(p))
	return out


func _texture_path(node, kind : int) -> String:
	var tex = null
	if kind in [1, 2, 3, 4]:
		tex = node.get("Texture")
	elif kind in [5, 6]:
		if node.has_method("get_texture"):
			tex = node.get_texture()
	elif kind == 8:
		tex = node.get("TilesTexture")
	elif kind == 7:
		# PatternShape uses its public shader texture property, not
		# Polygon2D.texture (confirmed in the installed 1.2.0.1 assembly).
		tex = node.get("_Texture")
	if tex != null and tex is Texture:
		return tex.resource_path
	return ""


func _asset_tex(category : String, asset):
	if typeof(asset) != TYPE_STRING or asset == "":
		return null
	return Script.GetAssetTexture(category, asset)


func _xy(req : Dictionary, fallback : Vector2) -> Vector2:
	if req.has("x") and req.has("y"):
		return Vector2(float(req["x"]), float(req["y"]))
	return fallback


func _vec(v : Vector2) -> Array:
	return [v.x, v.y]


func _points(raw) -> PoolVector2Array:
	var pts := PoolVector2Array()
	if typeof(raw) != TYPE_ARRAY:
		return pts
	for p in raw:
		if typeof(p) == TYPE_ARRAY and p.size() >= 2:
			pts.append(Vector2(float(p[0]), float(p[1])))
	return pts


# Accepts "#rrggbb" / "rrggbb" string, or [r,g,b] / [r,g,b,a] floats 0..1.
func _color(v, fallback : Color) -> Color:
	if typeof(v) == TYPE_STRING and v != "":
		return Color(v)
	if typeof(v) == TYPE_ARRAY and v.size() >= 3:
		var a = 1.0
		if v.size() >= 4:
			a = float(v[3])
		return Color(float(v[0]), float(v[1]), float(v[2]), a)
	return fallback


func _ok(result) -> Dictionary:
	return { "ok": true, "result": result }


func _err(msg) -> Dictionary:
	return { "ok": false, "error": msg }


func _register_tool():
	var icon = _ensure_icon()
	var panel = Global.Editor.Toolset.CreateModTool(self, "Settings", "mcp_bridge", "MCP Bridge", icon)
	panel.CreateLabel("Listening on")
	panel.CreateLabel("%s:%d" % [HOST, PORT])


func _ensure_icon() -> String:
	var dir = Directory.new()
	if not dir.dir_exists(Global.Root + "icons"):
		dir.make_dir(Global.Root + "icons")
	var path = Global.Root + "icons/mcp_bridge.png"
	var f = File.new()
	if not f.file_exists(path):
		var img = Image.new()
		img.create(32, 32, false, Image.FORMAT_RGBA8)
		img.fill(Color(0.18, 0.55, 0.95))
		img.save_png(path)
	return path


# Bounded native jobs. No scene lifecycle or irreversible edits in a batch.
const BATCH_SCHEMA_VERSION := 1
const MAX_BATCH_OPERATIONS := 500
const MAX_BATCH_JOBS := 64
const BATCH_OPERATIONS_PER_FRAME := 4
const BATCH_FRAME_BUDGET_USEC := 8000
const BATCH_FIELDS := {
	"set_water_settings": ["cmd", "deep_color", "shallow_color", "blend_distance", "border", "apply_to_existing"],
	"set_terrain_settings": ["cmd", "enabled", "smooth_blending"],
	"move_element": ["cmd", "id", "x", "y"],
	"modify_object": ["cmd", "id", "asset", "scale", "rotation", "shadow", "color", "layer"],
	"delete_object": ["cmd", "id"],
	"place_object": ["cmd", "asset", "x", "y", "scale", "rotation", "sorting", "color", "layer"],
	"draw_wall": ["cmd", "asset", "points", "loop", "shadow", "type", "joint", "color"],
	"draw_path": ["cmd", "asset", "points", "layer", "sorting", "width", "smoothness"],
	"add_light": ["cmd", "x", "y", "asset", "energy", "range", "shadows", "color"],
	"add_portal": ["cmd", "asset", "x", "y", "mount", "closed", "radius", "rotation"],
	"draw_water": ["cmd", "points", "erase"],
	"fill_region": ["cmd", "slot", "asset", "points", "rate"],
	"fill_terrain": ["cmd", "slot", "asset"],
	"paint_terrain": ["cmd", "slot", "asset", "x", "y", "radius", "rate"],
	"paint_path": ["cmd", "slot", "asset", "points", "radius", "rate"],
}
const BATCH_CATEGORIES := {"place_object": "Objects", "draw_wall": "Walls", "draw_path": "Paths", "add_light": "Lights", "add_portal": "Portals", "fill_terrain": "Terrain", "paint_terrain": "Terrain", "paint_path": "Terrain"}
const BATCH_READ_COMMANDS := ["get_water_settings", "get_terrain_settings", "get_surface_state", "get_export_status", "ping", "get_status", "get_map_info", "get_capabilities", "list_assets", "list_asset_metadata", "list_asset_categories", "list_elements", "get_element", "get_water", "list_levels", "get_camera", "apply_batch", "get_batch", "cancel_batch"]
var _batch_jobs := {}
var _batch_keys := {}
var _active_batch := ""
var _batch_sequence := 0
var _executing_batch := false


func _batch_number(value, low : float, high : float) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_REAL] and value >= low and value <= high


func _batch_integer(value, low : int, high : int) -> bool:
	return _batch_number(value, low, high) and floor(value) == value


func _batch_point(point) -> bool:
	return typeof(point) == TYPE_ARRAY and point.size() == 2 and _batch_number(point[0], 0, Global.World.WoxelDimensions.x) and _batch_number(point[1], 0, Global.World.WoxelDimensions.y)


func _batch_validate(op) -> Array:
	var errors := []
	if typeof(op) != TYPE_DICTIONARY:
		return ["operation must be an object"]
	var cmd = op.get("cmd", "")
	if typeof(cmd) != TYPE_STRING or not BATCH_FIELDS.has(cmd):
		return ["unsupported batch command"]
	for field in op:
		if not field in BATCH_FIELDS[cmd]:
			errors.append("unknown field: " + str(field))
	if cmd in ["set_water_settings", "set_terrain_settings"]:
		return errors + _settings_errors(op, cmd)
	if cmd in ["place_object", "add_light", "add_portal", "paint_terrain", "move_element"]:
		if not _batch_point([op.get("x"), op.get("y")]):
			errors.append("x/y must be finite coordinates within the map")
	if cmd in ["draw_wall", "draw_path", "paint_path", "fill_region", "draw_water"]:
		var points = op.get("points")
		if typeof(points) != TYPE_ARRAY or points.size() < 2 or points.size() > 32:
			errors.append("points must contain 2..32 coordinate pairs")
		else:
			for i in range(points.size()):
				if not _batch_point(points[i]):
					errors.append("point " + str(i) + " is invalid or outside the map")
				elif i > 0 and _batch_point(points[i - 1]) and Vector2(points[i][0], points[i][1]).distance_to(Vector2(points[i - 1][0], points[i - 1][1])) < 0.01:
					errors.append("consecutive points must differ")
			if cmd == "draw_wall" and op.get("loop", false) == true and points.size() < 3:
				errors.append("looped walls require at least three points")
	if cmd in ["fill_region", "draw_water"] and not _batch_polygon(op.get("points")):
		errors.append("polygon must be simple with 3..32 unique vertices and positive area")
	for field in ["loop", "shadow", "shadows", "closed", "erase"]:
		if op.has(field) and typeof(op[field]) != TYPE_BOOL:
			errors.append(field + " must be boolean")
	var ranges := {"scale": [0.01, 10], "rotation": [-36000, 36000], "width": [0.01, 10], "smoothness": [0, 1], "energy": [0, 10], "range": [0.01, 10], "radius": [1, 1024], "rate": [0, 1]}
	for field in ranges:
		if op.has(field) and not _batch_number(op[field], ranges[field][0], ranges[field][1]):
			errors.append(field + " is outside the batch limit")
	if op.has("layer"):
		var object_layer = cmd in ["place_object", "modify_object"]
		if not _batch_integer(op["layer"], -1000 if object_layer else 0, 1000 if object_layer else 3):
			errors.append("object layer must be -1000..1000; path layer must be 0..3")
	for field in ["sorting", "type", "joint", "slot"]:
		if op.has(field) and not _batch_integer(op[field], 0, 3):
			errors.append(field + " must be an integer in 0..3")
	if op.has("sorting") and not op["sorting"] in [0, 1]:
		errors.append("sorting must be 0 or 1")
	if cmd == "draw_wall" and (op.get("type", 0) != 0 or op.get("joint", 1) != 1):
		errors.append("batch walls use native type 0 and joint 1")
	if cmd == "add_portal" and op.get("mount") != "free":
		errors.append("only explicit mount=free portals are reversible in a batch")
	if op.has("color"):
		var color = op["color"]
		if typeof(color) == TYPE_STRING:
			var hex = color.trim_prefix("#").to_lower()
			var valid = hex.length() == 6
			for i in range(hex.length()):
				if "0123456789abcdef".find(hex.substr(i, 1)) == -1:
					valid = false
			if not valid:
				errors.append("color string must be six hexadecimal digits")
		elif typeof(color) == TYPE_ARRAY and color.size() in [3, 4]:
			for component in color:
				if not _batch_number(component, 0, 1):
					errors.append("color components must be in 0..1")
		else:
			errors.append("invalid color")
	if cmd in TERRAIN_CMDS:
		var slot = op.get("slot", 0)
		if _batch_integer(slot, 0, 3) and Global.World.GetCurrentLevel().Terrain.GetTexture(slot) == null:
			errors.append("terrain slot must have a native texture for rollback")
	if cmd in ["move_element", "modify_object", "delete_object"]:
		if not _batch_integer(op.get("id"), 0, 2147483647):
			errors.append("id must be a nonnegative integer")
		else:
			var node = Global.World.GetNodeByID(int(op["id"]))
			if node == null or node.get_parent() != Global.World.GetCurrentLevel().Objects:
				errors.append("batch transforms/deletion require an object on the current level")
		if cmd == "modify_object" and op.has("asset"):
			if typeof(op["asset"]) != TYPE_STRING or not _asset_catalog["Objects"].has(op["asset"]):
				errors.append("asset is not in the loaded Objects catalog")
			elif _asset_tex("Objects", op["asset"]) == null:
				errors.append("asset texture cannot be loaded")
		return errors
	if cmd == "draw_water":
		return errors
	var category = "Terrain" if cmd == "fill_region" else BATCH_CATEGORIES[cmd]
	if cmd != "add_light" or op.has("asset"):
		var asset = op.get("asset")
		if typeof(asset) != TYPE_STRING or not _asset_catalog[category].has(asset):
			errors.append("asset is not in the loaded " + category + " catalog")
		elif _asset_tex(category, asset) == null:
			errors.append("asset texture cannot be loaded")
	return errors


func _batch_canonical(value):
	if typeof(value) == TYPE_DICTIONARY:
		var result := {}
		var keys = value.keys()
		keys.sort()
		for key in keys:
			result[key] = _batch_canonical(value[key])
		return result
	if typeof(value) == TYPE_ARRAY:
		var result := []
		for item in value:
			result.append(_batch_canonical(item))
		return result
	return value


func _batch_summary(job : Dictionary, include_results : bool = true) -> Dictionary:
	var result := {"accepted": true, "schema_version": BATCH_SCHEMA_VERSION, "job_id": job["job_id"], "bridge_instance": _instance_id, "idempotency_key": job["key"], "status": job["status"], "total": job["operations"].size(), "processed": job["next"], "rollback_remaining": job["rollback_ops"].size(), "atomicity": "rollback_on_failure_or_cancel", "max_frame_ms": job["max_frame_ms"]}
	if include_results:
		result["results"] = job["results"]
	if job.has("error"):
		result["error"] = job["error"]
	return result


func _apply_batch(req : Dictionary) -> Dictionary:
	if req.get("schema_version") != BATCH_SCHEMA_VERSION:
		return _err("unsupported batch schema_version")
	var ops = req.get("operations")
	var key = req.get("idempotency_key")
	if typeof(ops) != TYPE_ARRAY or ops.empty() or ops.size() > MAX_BATCH_OPERATIONS:
		return _err("operations must contain 1..500 entries")
	if typeof(key) != TYPE_STRING or key.empty() or key.length() > 128:
		return _err("idempotency_key must contain 1..128 characters")
	var signature = JSON.print(_batch_canonical(ops))
	if _batch_keys.has(key):
		var previous = _batch_jobs[_batch_keys[key]]
		if previous["signature"] != signature:
			return _err("idempotency_key was already used with different operations")
		return _ok(_batch_summary(previous))
	if _active_batch != "" or not _pending_switch.empty():
		return _err("another edit job or map switch is active")
	if _batch_jobs.size() >= MAX_BATCH_JOBS:
		return _err("this map instance retained 64 jobs; save and reload before submitting more")
	var level = Global.World.GetCurrentLevel()
	if level == null or bool(_master().get("IsBusy")):
		return _err("map is unavailable or editor is busy")
	_ensure_asset_catalog()
	var errors := []
	var terrain_count := 0
	var water_count := 0
	for i in range(ops.size()):
		if typeof(ops[i]) == TYPE_DICTIONARY and ops[i].get("cmd") in TERRAIN_CMDS:
			terrain_count += 1
		if typeof(ops[i]) == TYPE_DICTIONARY and ops[i].get("cmd") in ["draw_water", "set_water_settings"]:
			water_count += 1
		for message in _batch_validate(ops[i]):
			errors.append({"index": i, "error": message})
	if terrain_count > 16:
		errors.append({"index": -1, "error": "at most 16 terrain operations per batch"})
	if water_count > 16:
		errors.append({"index": -1, "error": "at most 16 water operations per batch"})
	if not errors.empty():
		return _ok({"accepted": false, "schema_version": BATCH_SCHEMA_VERSION, "validation_errors": errors})
	_batch_sequence += 1
	var id = _instance_id + ":" + str(_batch_sequence)
	var job := {"job_id": id, "key": key, "signature": signature, "operations": ops.duplicate(true), "status": "queued", "next": 0, "results": [], "rollback_ops": [], "history_start": _undo_stack.size(), "redo_before": _redo_stack.duplicate(), "level_id": Global.World.GetCurrentLevel().ID, "max_frame_ms": 0.0, "cancel": false}
	_batch_jobs[id] = job
	_batch_keys[key] = id
	_active_batch = id
	return _ok(_batch_summary(job))


func _get_batch(req : Dictionary) -> Dictionary:
	var id = req.get("job_id", "")
	if not _batch_jobs.has(id):
		return _err("job is not retained in this map instance")
	return _ok(_batch_summary(_batch_jobs[id], bool(req.get("include_results", true))))


func _cancel_batch(req : Dictionary) -> Dictionary:
	var id = req.get("job_id", "")
	if not _batch_jobs.has(id):
		return _err("job is not retained in this map instance")
	var job = _batch_jobs[id]
	if job["status"] in ["queued", "running"]:
		job["cancel"] = true
	return _ok(_batch_summary(job))


func _finish_batch(job : Dictionary, status : String):
	job["status"] = status
	_active_batch = ""
	job["redo_before"] = []


func _rollback_batch(job : Dictionary, terminal_status : String):
	job["terminal_status"] = terminal_status
	job["status"] = "rolling_back"
	job["rollback_ops"] = _undo_stack.slice(job["history_start"], _undo_stack.size() - 1) if _undo_stack.size() > job["history_start"] else []


func _advance_batch():
	if _active_batch == "":
		return
	var job = _batch_jobs[_active_batch]
	if Global.World.GetCurrentLevel() == null or Global.World.GetCurrentLevel().ID != job["level_id"]:
		job["error"] = "level changed outside the bridge; partial state cannot be rolled back safely"
		_finish_batch(job, "failed_partial")
		return
	if job["cancel"] and job["status"] in ["queued", "running"]:
		_rollback_batch(job, "cancelled")
	var started = OS.get_ticks_usec()
	var count := 0
	while count < BATCH_OPERATIONS_PER_FRAME:
		if job["status"] == "rolling_back":
			if job["rollback_ops"].empty():
				_redo_stack = job["redo_before"]
				for result in job["results"]:
					result["status"] = "rolled_back"
				_finish_batch(job, job["terminal_status"])
				break
			var op = job["rollback_ops"].back()
			if not _apply_op(op, true):
				job["error"] = "rollback failed; inspect retained results before retrying"
				_finish_batch(job, "failed_partial")
				break
			if op["kind"] == "create" and is_instance_valid(op["node"]):
				op["node"].queue_free()
			job["results"][job["rollback_ops"].size() - 1]["status"] = "rolled_back"
			job["rollback_ops"].pop_back()
			_undo_stack.pop_back()
		else:
			if job["next"] == job["operations"].size():
				_finish_batch(job, "completed")
				break
			job["status"] = "running"
			var index = job["next"]
			_executing_batch = true
			var response = _record_and_dispatch(job["operations"][index])
			_executing_batch = false
			if not response.get("ok", false):
				job["error"] = {"index": index, "message": response.get("error", "operation failed")}
				_rollback_batch(job, "failed")
			else:
				job["results"].append({"index": index, "cmd": job["operations"][index]["cmd"], "status": "applied", "result": response["result"]})
				job["next"] += 1
		count += 1
		if OS.get_ticks_usec() - started >= BATCH_FRAME_BUDGET_USEC:
			break
	job["max_frame_ms"] = max(job["max_frame_ms"], float(OS.get_ticks_usec() - started) / 1000.0)


# Add a native water polygon. DrawPolygon's inverse erases just the added area;
# loading the snapshot then restores any preexisting overlap. Load(empty Save)
# alone is insufficient because native WaterMesh.Load ignores a missing tree.
func _draw_water(req : Dictionary) -> Dictionary:
	if Global.World.GetCurrentLevel() == null:
		return _err("no map open")
	var errors = _batch_validate({"cmd": "draw_water", "points": req.get("points"), "erase": req.get("erase", false)})
	if not errors.empty():
		return _err(JSON.print(errors))
	var mesh = Global.World.GetCurrentLevel().WaterMesh
	mesh.DrawPolygon(_points(req["points"]), bool(req.get("erase", false)))
	return _ok({"water_added": not bool(req.get("erase", false)), "point_count": req["points"].size()})


# Appearance settings are separate from geometry and brush activation. Native
# WaterMesh colors are drawing defaults; existing regions store their own colors.
func _settings_errors(req : Dictionary, cmd : String) -> Array:
	var errors := []
	var fields = ["deep_color", "shallow_color", "blend_distance", "border"] if cmd == "set_water_settings" else ["enabled", "smooth_blending"]
	var supplied = false
	for field in fields:
		if req.has(field): supplied = true
	if not supplied: errors.append("supply at least one appearance setting")
	for field in ["enabled", "smooth_blending", "border", "apply_to_existing"]:
		if req.has(field) and typeof(req[field]) != TYPE_BOOL:
			errors.append(field + " must be boolean")
	for field in ["deep_color", "shallow_color"]:
		if req.has(field):
			var value = req[field]
			var valid = typeof(value) == TYPE_STRING
			if valid:
				var hex = value.trim_prefix("#").to_lower()
				valid = hex.length() == 6
				for i in range(hex.length()):
					if "0123456789abcdef".find(hex.substr(i, 1)) == -1: valid = false
			if not valid: errors.append(field + " must be a six-digit #RRGGBB color")
	if req.has("blend_distance") and not _batch_number(req["blend_distance"], 0, 10):
		errors.append("blend_distance must be finite and in 0..10 native slider units")
	return errors


func _terrain_settings_data() -> Dictionary:
	var terrain = Global.World.GetCurrentLevel().Terrain
	return {"enabled": terrain.visible, "smooth_blending": terrain.SmoothBlending, "expanded_slots": terrain.ExpandedSlots}


func _get_terrain_settings() -> Dictionary:
	if Global.World.GetCurrentLevel() == null: return _err("no map open")
	var data = _terrain_settings_data()
	data["level_id"] = Global.World.GetCurrentLevel().ID
	return _ok(data)


func _apply_terrain_settings(data : Dictionary):
	var terrain = Global.World.GetCurrentLevel().Terrain
	var brush = Global.Editor.Tools["TerrainBrush"]
	brush.SetEnabled(data["enabled"])
	terrain.visible = data["enabled"]
	brush.SetSmoothBlending(data["smooth_blending"])
	terrain.SetSmoothBlending(data["smooth_blending"])


func _set_terrain_settings(req : Dictionary) -> Dictionary:
	if Global.World.GetCurrentLevel() == null: return _err("no map open")
	var errors = _batch_validate(req)
	if not errors.empty(): return _err(JSON.print(errors))
	var data = _terrain_settings_data()
	for field in ["enabled", "smooth_blending"]:
		if req.has(field): data[field] = req[field]
	_apply_terrain_settings(data)
	return _get_terrain_settings()


func _water_defaults(with_alpha : bool = false) -> Dictionary:
	var mesh = Global.World.GetCurrentLevel().WaterMesh
	return {"deep_color": "#" + mesh.DeepColor.to_html(with_alpha), "shallow_color": "#" + mesh.ShallowColor.to_html(with_alpha), "blend_distance": mesh.BlendDistance}


func _set_water_defaults(data : Dictionary):
	var mesh = Global.World.GetCurrentLevel().WaterMesh
	mesh.DeepColor = Color(data["deep_color"])
	mesh.ShallowColor = Color(data["shallow_color"])
	mesh.BlendDistance = data["blend_distance"]


func _water_settings_snapshot() -> Dictionary:
	return {"data": Global.World.GetCurrentLevel().WaterMesh.Save().duplicate(true), "defaults": _water_defaults(true)}


func _restore_water_settings(snapshot : Dictionary, restore_regions : bool = true):
	var mesh = Global.World.GetCurrentLevel().WaterMesh
	if restore_regions and snapshot["data"].has("tree"):
		mesh.Load(snapshot["data"].duplicate(true))
	Global.Editor.Tools["WaterBrush"].SetDisableBorder(snapshot["data"].get("disable_border", false))
	_set_water_defaults(snapshot["defaults"])


# Save/Load dictionaries retain native PoolVector2Array geometry. Never convert
# polygon coordinates through strings or reconstruct regions to change styling.
# The root is depth 0, filled regions have odd depth, and holes have even depth.
func _water_regions(node : Dictionary, path : Array, regions : Array):
	if path.size() % 2 == 1 and not node.get("is_open", false):
		regions.append({"tree_path": path.duplicate(), "deep_color": node.get("deep_color"), "shallow_color": node.get("shallow_color"), "blend_distance": node.get("blend_distance")})
	var children = node.get("children", [])
	for i in range(children.size()):
		_water_regions(children[i], path + [i], regions)


func _recolor_water(node : Dictionary, depth : int, req : Dictionary):
	if depth % 2 == 1 and not node.get("is_open", false):
		for field in ["deep_color", "shallow_color"]:
			if req.has(field):
				# Dungeondraft native serialization uses AARRGGBB, not RRGGBBAA.
				node[field] = "ff" + req[field].trim_prefix("#").to_lower()
		if req.has("blend_distance"): node["blend_distance"] = float(req["blend_distance"])
	for child in node.get("children", []):
		_recolor_water(child, depth + 1, req)


func _water_geometry(value):
	if typeof(value) == TYPE_DICTIONARY:
		var result := {}
		for key in value:
			if not key in ["ref", "deep_color", "shallow_color", "blend_distance", "disable_border"]:
				result[key] = _water_geometry(value[key])
		return result
	if typeof(value) == TYPE_ARRAY:
		var result := []
		for item in value: result.append(_water_geometry(item))
		return result
	return value


func _get_water_settings() -> Dictionary:
	if Global.World.GetCurrentLevel() == null: return _err("no map open")
	var saved = Global.World.GetCurrentLevel().WaterMesh.Save()
	var regions := []
	if saved.has("tree"): _water_regions(saved["tree"], [], regions)
	return _ok({"level_id": Global.World.GetCurrentLevel().ID, "defaults": _water_defaults(), "border": not saved.get("disable_border", false), "regions": regions, "region_color_format": "AARRGGBB"})


func _set_water_settings(req : Dictionary) -> Dictionary:
	if Global.World.GetCurrentLevel() == null: return _err("no map open")
	var errors = _batch_validate(req)
	if not errors.empty(): return _err(JSON.print(errors))
	var before = _water_settings_snapshot()
	var snapshot = before.duplicate(true)
	for field in ["deep_color", "shallow_color", "blend_distance"]:
		if req.has(field): snapshot["defaults"][field] = req[field]
	if req.get("apply_to_existing", true) and snapshot["data"].has("tree"):
		_recolor_water(snapshot["data"]["tree"], 0, req)
	if req.has("border"): snapshot["data"]["disable_border"] = not req["border"]
	var restyle = req.get("apply_to_existing", true) and (req.has("deep_color") or req.has("shallow_color") or req.has("blend_distance"))
	_restore_water_settings(snapshot, restyle)
	var after = Global.World.GetCurrentLevel().WaterMesh.Save()
	if JSON.print(_batch_canonical(_water_geometry(before["data"]))) != JSON.print(_batch_canonical(_water_geometry(after))):
		_restore_water_settings(before)
		return _err("water geometry changed during styling; restored the previous snapshot")
	return _get_water_settings()


func _batch_polygon(points) -> bool:
	if typeof(points) != TYPE_ARRAY or points.size() < 3 or points.size() > 32:
		return false
	for point in points:
		if not _batch_point(point):
			return false
	var area := 0.0
	for i in range(points.size()):
		if not _batch_point(points[i]):
			return false
		var a = Vector2(points[i][0], points[i][1])
		var next = points[(i + 1) % points.size()]
		if not _batch_point(next):
			return false
		var b = Vector2(next[0], next[1])
		var previous = points[(i + points.size() - 1) % points.size()]
		var incoming = Vector2(previous[0], previous[1]) - a
		var outgoing = b - a
		# Adjacent edges may share their endpoint, but must not backtrack.
		if abs(incoming.cross(outgoing)) < 0.01 and incoming.dot(outgoing) > 0.0:
			return false
		area += a.cross(b)
		for j in range(i + 1, points.size()):
			if a.distance_to(Vector2(points[j][0], points[j][1])) < 0.01:
				return false
		for j in range(i + 1, points.size()):
			if j == i + 1 or (i == 0 and j == points.size() - 1):
				continue
			var c = Vector2(points[j][0], points[j][1])
			var d = Vector2(points[(j + 1) % points.size()][0], points[(j + 1) % points.size()][1])
			if abs((b - a).cross(c - a)) < 0.01 and abs((b - a).cross(d - a)) < 0.01 and max(min(a.x, b.x), min(c.x, d.x)) <= min(max(a.x, b.x), max(c.x, d.x)) and max(min(a.y, b.y), min(c.y, d.y)) <= min(max(a.y, b.y), max(c.y, d.y)):
				return false
			if Geometry.segment_intersects_segment_2d(a, b, c, d) != null:
				return false
	return abs(area) > 1.0 and Geometry.triangulate_polygon(_points(points)).size() > 0
