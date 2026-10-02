"""Strict versioned intermediate format. Grid units are tiles, never pixels."""

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Point = Annotated[list[FiniteFloat], Field(min_length=2, max_length=2)]
Polygon = Annotated[list[Point], Field(min_length=3, max_length=24)]
Polyline = Annotated[list[Point], Field(min_length=2, max_length=12)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Size(Closed):
    width: int = Field(ge=8, le=128)
    height: int = Field(ge=8, le=128)


class Gameplay(Closed):
    movement_cost: FiniteFloat = Field(default=1, ge=1, le=10)
    cover: Literal["none", "half", "three_quarters", "full"] = "none"
    blocks_movement: bool = False
    notes: str = Field(default="", max_length=1024)


class Feature(Closed):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    gameplay: Gameplay = Field(default_factory=Gameplay)


class Road(Feature):
    type: Literal["road"]
    points: Polyline
    width: FiniteFloat = Field(default=2, gt=0, le=8)
    material: str = "dirt"
    smooth: bool = True
    clearance: FiniteFloat = Field(default=0.25, ge=0, le=4)


class Stream(Feature):
    type: Literal["stream"]
    points: Polyline
    width: FiniteFloat = Field(default=1.5, gt=0, le=8)
    smooth: bool = True
    depth: Literal["shallow", "deep"] = "shallow"


class TerrainRegion(Feature):
    type: Literal["terrain_region"]
    region: Polygon
    material: str


class Forest(Feature):
    type: Literal["forest"]
    region: Polygon
    count: int = Field(ge=1, le=400)
    tree_types: list[str] = Field(
        default_factory=lambda: ["oak"], min_length=1, max_length=8
    )
    scale: FiniteFloat = Field(default=0.35, ge=0.05, le=3)
    min_spacing: FiniteFloat = Field(default=1.8, ge=0.25, le=16)


class Prop(Feature):
    type: Literal["cover", "obstacle", "hazard"]
    position: Point
    radius: FiniteFloat = Field(default=0.5, gt=0, le=8)
    asset: str = "boulder"
    scale: FiniteFloat = Field(default=0.5, ge=0.05, le=3)
    rotation: FiniteFloat = Field(default=0, ge=-360, le=360)


class ClearArea(Feature):
    type: Literal["clear_area"]
    region: Polygon
    purpose: Literal["encounter", "crossing"] = "encounter"


class Zone(Feature):
    type: Literal["entry", "spawn"]
    position: Point
    radius: FiniteFloat = Field(default=1, gt=0, le=8)


class Door(Closed):
    position: Point
    width: FiniteFloat = Field(default=1.5, ge=1, le=4)


class Building(Feature):
    type: Literal["building", "room"]
    region: Polygon
    doors: list[Door] = Field(default_factory=list, max_length=8)
    wall_asset: str = "stone"
    floor_material: str = "gravel"


class Output(Closed):
    ppi: int = Field(default=64, ge=16, le=256)
    grid: bool = False


class Encounter(Closed):
    required_routes: list[Annotated[list[str], Field(min_length=2, max_length=2)]] = (
        Field(default_factory=list, max_length=16)
    )
    agent_radius: FiniteFloat = Field(default=0.4, ge=0.1, le=2)


FeatureSpec = Annotated[
    Union[Road, Stream, TerrainRegion, Forest, Prop, ClearArea, Zone, Building],
    Field(discriminator="type"),
]


class MapSpec(Closed):
    schema_version: Literal["map_spec.v1"]
    units: Literal["tiles"] = "tiles"
    size: Size
    seed: int = Field(ge=0, le=2147483647)
    biome: str = Field(default="temperate_forest", max_length=128)
    theme: str = Field(default="", max_length=128)
    base_material: str | None = "grass"
    margin: FiniteFloat = Field(default=0.25, ge=0, le=4)
    features: list[FeatureSpec] = Field(min_length=1, max_length=64)
    encounter: Encounter = Field(default_factory=Encounter)
    output: Output = Field(default_factory=Output)
    asset_overrides: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def identities(self):
        ids = [f.id for f in self.features]
        if len(set(ids)) != len(ids):
            raise ValueError("feature IDs must be unique")
        positions = {f.id for f in self.features if isinstance(f, Zone)}
        for route in self.encounter.required_routes:
            if not set(route) <= positions:
                raise ValueError(
                    "required_routes must reference entry/spawn feature IDs"
                )
        return self
