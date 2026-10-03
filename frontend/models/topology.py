"""
Grid Topology and Geospatial Network Model with 3-Zone Architecture.
Zone 0: Power Station & Grid Substation Hub (with IoT telemetry)
Zone 1: North City Sector (Commercial & Residential)
Zone 2: South City Sector (Suburban Residential)
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import networkx as nx
from config import CONFIG


@dataclass
class Coordinate:
    lat: float
    lon: float
    elevation_m: float = 0.0

    def distance_to(self, other: Coordinate) -> float:
        """Haversine formula to compute great-circle distance in meters."""
        r = 6371000.0
        phi1 = math.radians(self.lat)
        phi2 = math.radians(other.lat)
        delta_phi = math.radians(other.lat - self.lat)
        delta_lambda = math.radians(other.lon - self.lon)

        a = (
            math.sin(delta_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        horiz_dist = r * c
        vert_dist = other.elevation_m - self.elevation_m
        return math.sqrt(horiz_dist**2 + vert_dist**2)

    def to_dict(self) -> Dict[str, float]:
        return {"lat": self.lat, "lon": self.lon, "elevation_m": self.elevation_m}


@dataclass
class PowerStationNode:
    """Zone 0: Power Generation & Primary Substation Hub with IoT sensors."""
    id: str
    name: str
    zone_id: str
    coordinate: Coordinate
    capacity_mva: float
    transmission_voltage_kv: float
    primary_feeder_voltage_kv: float
    footprint_polygon: List[List[float]] = field(default_factory=list)
    building_height_m: float = 12.0
    feeder_ids: List[str] = field(default_factory=list)
    # IoT Real-time monitoring metrics
    iot_sensors: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "zone_id": self.zone_id,
            "coordinate": self.coordinate.to_dict(),
            "capacity_mva": self.capacity_mva,
            "transmission_voltage_kv": self.transmission_voltage_kv,
            "primary_feeder_voltage_kv": self.primary_feeder_voltage_kv,
            "footprint_polygon": self.footprint_polygon,
            "building_height_m": self.building_height_m,
            "feeder_ids": self.feeder_ids,
            "iot_sensors": self.iot_sensors,
        }


@dataclass
class TransmissionPylon:
    """High-voltage lattice towers running from Power Station to distribution centers."""
    id: str
    coordinate: Coordinate
    height_m: float = 24.0
    feeder_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "coordinate": self.coordinate.to_dict(),
            "height_m": self.height_m,
            "feeder_id": self.feeder_id,
        }


@dataclass
class RoadSegment:
    """City street grid geometries for authentic map visualization."""
    id: str
    name: str
    coordinates: List[List[float]] # [[lon, lat], ...]
    width_m: float = 10.0
    road_type: str = "avenue"      # "highway", "avenue", "residential"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "coordinates": self.coordinates,
            "width_m": self.width_m,
            "road_type": self.road_type,
        }


@dataclass
class ConsumerNode:
    id: str
    meter_id: str
    name: str
    category: str               # "Residential", "Commercial", "LightIndustrial"
    contracted_load_kw: float
    coordinate: Coordinate
    building_polygon: List[List[float]] # GeoJSON [[lon, lat], ...]
    building_height_m: float
    zone_id: str                # "Zone_1_North", "Zone_2_South"
    transformer_id: str
    feeder_id: str
    line_distance_m: float = 0.0
    phase: str = "R"            # "R", "Y", "B"
    connected_pole_id: Optional[str] = None
    kaggle_id: Optional[str] = None
    kaggle_flag: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "meter_id": self.meter_id,
            "name": self.name,
            "category": self.category,
            "contracted_load_kw": self.contracted_load_kw,
            "coordinate": self.coordinate.to_dict(),
            "building_polygon": self.building_polygon,
            "building_height_m": self.building_height_m,
            "zone_id": self.zone_id,
            "transformer_id": self.transformer_id,
            "feeder_id": self.feeder_id,
            "line_distance_m": self.line_distance_m,
            "phase": self.phase,
            "connected_pole_id": self.connected_pole_id,
            "kaggle_id": self.kaggle_id,
            "kaggle_flag": self.kaggle_flag,
        }


@dataclass
class DistributionPole:
    id: str
    coordinate: Coordinate
    feeder_id: str
    transformer_id: str
    connected_consumer_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "coordinate": self.coordinate.to_dict(),
            "feeder_id": self.feeder_id,
            "transformer_id": self.transformer_id,
            "connected_consumers": len(self.connected_consumer_ids),
            "connected_consumer_ids": self.connected_consumer_ids,
        }


@dataclass
class TransformerNode:
    id: str
    name: str
    zone_id: str
    coordinate: Coordinate
    capacity_kva: float
    feeder_id: str
    rated_voltage_kv: float = 11.0 / 0.415
    connected_consumer_ids: List[str] = field(default_factory=list)
    pole_ids: List[str] = field(default_factory=list)
    iot_sensors: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "zone_id": self.zone_id,
            "coordinate": self.coordinate.to_dict(),
            "capacity_kva": self.capacity_kva,
            "feeder_id": self.feeder_id,
            "rated_voltage_kv": self.rated_voltage_kv,
            "consumer_count": len(self.connected_consumer_ids),
            "connected_consumer_ids": self.connected_consumer_ids,
            "pole_ids": self.pole_ids,
            "iot_sensors": self.iot_sensors,
        }


@dataclass
class FeederNode:
    id: str
    name: str
    substation_id: str
    coordinate: Coordinate
    transformer_ids: List[str] = field(default_factory=list)


class GridTopology:
    """Represents the entire physical and electrical topology across the 3 zones."""

    def __init__(self):
        self.power_station: Optional[PowerStationNode] = None
        self.pylons: Dict[str, TransmissionPylon] = {}
        self.roads: Dict[str, RoadSegment] = {}
        self.feeders: Dict[str, FeederNode] = {}
        self.transformers: Dict[str, TransformerNode] = {}
        self.poles: Dict[str, DistributionPole] = {}
        self.consumers: Dict[str, ConsumerNode] = {}
        self.graph = nx.DiGraph()

    def set_power_station(self, station: PowerStationNode):
        self.power_station = station
        self.graph.add_node(
            station.id,
            type="power_station",
            coord=station.coordinate,
            name=station.name,
            data=station,
        )

    def add_pylon(self, pylon: TransmissionPylon):
        self.pylons[pylon.id] = pylon
        self.graph.add_node(pylon.id, type="pylon", data=pylon)

    def add_road(self, road: RoadSegment):
        self.roads[road.id] = road

    def add_feeder(self, feeder: FeederNode):
        self.feeders[feeder.id] = feeder
        self.graph.add_node(feeder.id, type="feeder", data=feeder)
        if self.power_station:
            self.graph.add_edge(self.power_station.id, feeder.id, edge_type="primary_distribution_11kv")

    def add_transformer(self, transformer: TransformerNode):
        self.transformers[transformer.id] = transformer
        self.graph.add_node(transformer.id, type="transformer", data=transformer)
        if transformer.feeder_id in self.feeders:
            self.feeders[transformer.feeder_id].transformer_ids.append(transformer.id)
            self.graph.add_edge(transformer.feeder_id, transformer.id, edge_type="11kv_stepdown")

    def add_pole(self, pole: DistributionPole):
        self.poles[pole.id] = pole
        self.graph.add_node(pole.id, type="pole", data=pole)
        if pole.transformer_id in self.transformers:
            self.transformers[pole.transformer_id].pole_ids.append(pole.id)
            self.graph.add_edge(pole.transformer_id, pole.id, edge_type="lv_main_line")

    def add_consumer(self, consumer: ConsumerNode, pole_id: Optional[str] = None):
        consumer.connected_pole_id = pole_id
        self.consumers[consumer.id] = consumer
        self.graph.add_node(consumer.id, type="consumer", data=consumer)
        if consumer.transformer_id in self.transformers:
            self.transformers[consumer.transformer_id].connected_consumer_ids.append(consumer.id)

        if pole_id and pole_id in self.poles:
            self.poles[pole_id].connected_consumer_ids.append(consumer.id)
            self.graph.add_edge(pole_id, consumer.id, edge_type="service_drop")
        else:
            self.graph.add_edge(consumer.transformer_id, consumer.id, edge_type="service_drop")

    def get_consumers_in_zone(self, zone_id: str) -> List[ConsumerNode]:
        return [c for c in self.consumers.values() if c.zone_id == zone_id]

    def get_consumers_under_transformer(self, transformer_id: str) -> List[ConsumerNode]:
        return [c for c in self.consumers.values() if c.transformer_id == transformer_id]

    def get_topology_summary(self) -> Dict[str, Any]:
        return {
            "power_station": self.power_station.id if self.power_station else "None",
            "feeders": len(self.feeders),
            "transformers": len(self.transformers),
            "pylons": len(self.pylons),
            "poles": len(self.poles),
            "consumers": len(self.consumers),
            "roads": len(self.roads),
            "zones": [CONFIG.ZONE_POWER_STATION, CONFIG.ZONE_CITY_NORTH, CONFIG.ZONE_CITY_SOUTH],
        }
