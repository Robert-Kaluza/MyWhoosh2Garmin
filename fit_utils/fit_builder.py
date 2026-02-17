import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator, computed_field
# Note: Ensure you have your specific FIT library installed
# (e.g., fit-tool or similar names used in your environment)
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Event,
    EventType,
    FileType,
    Intensity,
    Manufacturer,
    Sport,
    SubSport,
    GarminProduct,
)


class ActivityData(BaseModel):
    """Model for MyWhoosh activity JSON data."""

    model_config = ConfigDict(
        extra="forbid",  # Forbid extra fields
        validate_assignment=True,  # Validate on attribute assignment
        str_to_lower=True,  # Convert strings to lowercase
        strict=True,  # Enforce strict type checking
    )

    # From activity metadata api
    name: str = Field(default_factory=str, alias="strava_activity_name")
    id: int = Field(..., alias="strava_activity_id")
    activity_distance: float
    moving_time: int
    elapsed_time: int
    total_elevation_gain: float
    type: str
    start_date: datetime | int
    start_date_local: datetime | int
    timezone: str
    utc_offset: float
    average_speed: float
    max_speed: float
    average_cadence: float
    average_watts: float
    max_watts: int
    weighted_average_watts: int
    kilojoules: float
    # HEART RATE FIX: Make these optional
    average_heartrate: Optional[float] = None
    max_heartrate: Optional[float] = None
    calories: float

    # From streams
    lat: List[float]
    long: List[float]
    watts: List[int]
    cadence: List[int]
    velocity_smooth: List[float]
    time: List[int]
    distance: List[float]
    # HEART RATE FIX: Default to empty lists
    heartrate: List[int] = Field(default_factory=list)
    heartrates: List[int] = Field(default_factory=list)
    grade_smooth: Optional[List[float]] = None
    altitude: Optional[List[float]] = None

    @model_validator(mode="after")
    def validate_streams(self) -> "ActivityData":
        """Validate that all stream lists have the same length and records exist."""
        # Fields that MUST exist and match in length
        required_stream_attrs = [
            "lat", "long", "watts", "cadence",
            "velocity_smooth", "time", "distance"
        ]

        # Fields that might be empty or None
        optional_stream_attrs = ["heartrate", "heartrates", "grade_smooth", "altitude"]

        # Calculate base length from 'time'
        base_length = len(self.time)

        # Check required
        for attr in required_stream_attrs:
            if len(getattr(self, attr)) != base_length:
                raise ValueError(f"Stream '{attr}' length does not match 'time' length.")

        # Check optional (only if they are populated)
        for attr in optional_stream_attrs:
            val = getattr(self, attr)
            if val is not None and len(val) > 0:
                if len(val) != base_length:
                    raise ValueError(f"Stream '{attr}' length does not match 'time' length.")

        return self

    @property
    def stream_length(self) -> int:
        return len(self.time)

    @property
    def elapsed_time_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        return self.elapsed_time * 1000

    @classmethod
    def from_json_file(cls, json_file_path: str) -> "ActivityData":
        """Load and parse the JSON activity file into the model."""
        with open(json_file_path, "r") as f:
            raw_data = json.load(f)

        metadata = raw_data.get("metadata", {})
        streams = raw_data.get("streams", {})

        # Extract lat/long safely
        lat_values = []
        long_values = []
        latlng_data = streams.get("latlng", {}).get("data", [])
        if latlng_data:
            lat_values, long_values = zip(*latlng_data)

        combined_data = {
            "strava_activity_name": metadata.get("name", ""),
            "strava_activity_id": metadata.get("id"),
            "activity_distance": metadata.get("distance"),
            "moving_time": metadata.get("moving_time"),
            "elapsed_time": metadata.get("elapsed_time"),
            "total_elevation_gain": metadata.get("total_elevation_gain"),
            "type": metadata.get("type"),
            "start_date": datetime.fromisoformat(metadata.get("start_date")) if metadata.get("start_date") else None,
            "start_date_local": datetime.fromisoformat(metadata.get("start_date_local")) if metadata.get("start_date_local") else None,
            "timezone": metadata.get("timezone"),
            "utc_offset": metadata.get("utc_offset"),
            "average_speed": metadata.get("average_speed"),
            "max_speed": metadata.get("max_speed"),
            "average_cadence": metadata.get("average_cadence"),
            "average_watts": metadata.get("average_watts"),
            "max_watts": metadata.get("max_watts"),
            "weighted_average_watts": metadata.get("weighted_average_watts"),
            "kilojoules": metadata.get("kilojoules"),
            "average_heartrate": metadata.get("average_heartrate"),
            "max_heartrate": metadata.get("max_heartrate"),
            "calories": metadata.get("calories"),
            "lat": list(lat_values),
            "long": list(long_values),
            "watts": streams.get("watts", {}).get("data", []),
            "cadence": streams.get("cadence", {}).get("data", []),
            "velocity_smooth": streams.get("velocity_smooth", {}).get("data", []),
            "time": streams.get("time", {}).get("data", []),
            "distance": streams.get("distance", {}).get("data", []),
            "heartrate": streams.get("heartrate", {}).get("data", []),
            "heartrates": streams.get("heartrate", {}).get("data", []),
            "grade_smooth": streams.get("grade_smooth", {}).get("data"),
            "altitude": streams.get("altitude", {}).get("data"),
        }

        return cls(**combined_data)

    @computed_field
    def max_cadence(self) -> int:
        return max(self.cadence) if self.cadence else 0

    @computed_field
    @property
    def start_ts_miliseconds(self) -> int:
        return round(self.start_date.timestamp()) * 1000


class MyWhooshFitBuilder:
    """Convert MyWhoosh activity JSON to FIT file format."""

    def __init__(self, json_file_path: str):
        """Initialize with path to MyWhoosh JSON file."""
        self.json_path = json_file_path
        self.activity_data = ActivityData.from_json_file(json_file_path)
        self.builder = FitFileBuilder(auto_define=True)
        self.end_date_fit_ts = (
            self.activity_data.start_ts_miliseconds
            + 1000 * self.activity_data.stream_length
        )

    def _add_file_id(self):
        """Add file_id message."""
        file_id = FileIdMessage()
        file_id.type = FileType.ACTIVITY
        file_id.manufacturer = Manufacturer.GARMIN.value
        file_id.product = GarminProduct.EDGE_530.value
        file_id.serial_number = 3313379353
        file_id.time_created = self.activity_data.start_ts_miliseconds
        self.builder.add(file_id)

    def _add_file_creator(self):
        """Add file creator message."""
        file_creator = FileCreatorMessage()
        file_creator.software_version = 29
        self.builder.add(file_creator)

    def _add_event(self, timestamp: int, event: Event, event_type: EventType):
        """Add event message."""
        event_msg = EventMessage()
        event_msg.timestamp = timestamp
        event_msg.event = event
        event_msg.event_type = event_type
        self.builder.add(event_msg)

    def _add_records(self):
        """Add all record messages from the activity data."""
        if not self.activity_data or self.activity_data.stream_length == 0:
            return

        for i in range(self.activity_data.stream_length):
            record = RecordMessage()

            # Timestamp - time[i] est en secondes, on convertit en millisecondes
            record.timestamp = self.activity_data.start_ts_miliseconds + (
                self.activity_data.time[i] * 1000
            )

            # Position (lat/long en degrés)
            record.position_lat = self.activity_data.lat[i]
            record.position_long = self.activity_data.long[i]
            record.distance = self.activity_data.distance[i]
            record.cadence = self.activity_data.cadence[i]
            record.power = self.activity_data.watts[i]
            record.speed = self.activity_data.velocity_smooth[i]

            # HEART RATE FIX: Only add if list is not empty
            if self.activity_data.heartrate:
                record.heart_rate = self.activity_data.heartrate[i]

            if self.activity_data.altitude is not None:
                record.altitude = self.activity_data.altitude[i]

            self.builder.add(record)

    def _add_lap(self):
        lap = LapMessage()
        lap.timestamp = self.activity_data.start_ts_miliseconds + self.activity_data.elapsed_time_ms
        lap.start_time = self.activity_data.start_ts_miliseconds
        lap.total_elapsed_time = self.activity_data.elapsed_time
        lap.total_timer_time = self.activity_data.elapsed_time
        lap.intensity = Intensity.ACTIVE
        lap.total_distance = self.activity_data.activity_distance

        # HEART RATE FIX: Check for None
        if self.activity_data.average_heartrate is not None:
            lap.avg_heart_rate = int(self.activity_data.average_heartrate)
        if self.activity_data.max_heartrate is not None:
            lap.max_heart_rate = int(self.activity_data.max_heartrate)

        lap.avg_cadence = int(self.activity_data.average_cadence)
        lap.max_cadence = int(self.activity_data.max_cadence)

        lap.avg_power = int(self.activity_data.average_watts)
        lap.max_power = int(self.activity_data.max_watts)

        lap.avg_speed = self.activity_data.average_speed
        lap.max_speed = self.activity_data.max_speed

        lap.total_calories = int(self.activity_data.calories)
        lap.sport = Sport.CYCLING
        lap.sub_sport = SubSport.VIRTUAL_ACTIVITY

        self.builder.add(lap)

    def _add_session(self):
        """Add session message."""
        session = SessionMessage()

        session.timestamp = self.end_date_fit_ts
        session.start_time = self.activity_data.start_ts_miliseconds
        session.total_elapsed_time = self.activity_data.elapsed_time
        session.total_timer_time = self.activity_data.elapsed_time
        session.total_distance = self.activity_data.activity_distance

        # HEART RATE FIX: Check for None
        if self.activity_data.average_heartrate is not None:
            session.avg_heart_rate = int(self.activity_data.average_heartrate)
        if self.activity_data.max_heartrate is not None:
            session.max_heart_rate = int(self.activity_data.max_heartrate)

        session.avg_cadence = int(self.activity_data.average_cadence)
        session.max_cadence = int(self.activity_data.max_cadence)

        session.avg_power = int(self.activity_data.average_watts)
        session.max_power = int(self.activity_data.max_watts)

        session.avg_speed = self.activity_data.average_speed
        session.max_speed = self.activity_data.max_speed

        session.total_calories = int(self.activity_data.calories)
        session.sport = Sport.CYCLING
        session.sub_sport = SubSport.VIRTUAL_ACTIVITY
        session.first_lap_index = 0
        session.num_laps = 1

        self.builder.add(session)

    def _add_activity(self):
        """Add activity message."""
        activity = ActivityMessage()
        activity.timestamp = self.end_date_fit_ts
        activity.total_timer_time = self.activity_data.elapsed_time
        activity.num_sessions = 1
        activity.type = 0
        activity.event = Event.ACTIVITY
        activity.event_type = EventType.STOP
        activity.local_timestamp = round(self.activity_data.start_date.timestamp())
        self.builder.add(activity)

    def build(self, output_path: str = None):
        """Build and write the FIT file."""
        if not output_path:
            raise ValueError("output_path is required.")

        # Add messages in order
        self._add_file_id()
        self._add_file_creator()
        self._add_event(self.activity_data.start_ts_miliseconds, Event.TIMER, EventType.START)
        self._add_records()

        # Add lap
        self._add_lap()

        # Timer stop event
        self._add_event(self.end_date_fit_ts, Event.SESSION, EventType.STOP_DISABLE_ALL)

        # Add session and activity
        self._add_session()
        self._add_activity()

        # Build FIT file and write to disk
        fit_file = self.builder.build()

        # Ensure the output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        fit_file.to_file(output_path)

        print(f"FIT file saved to: {output_path}")


# Example usage
if __name__ == "__main__":
    data_dir = Path(__file__).parent.parent / "data"
    input_file = str(data_dir / "raw" / "your_activity.json")
    output_file = str(data_dir / "processed" / "your_activity.fit")

    if Path(input_file).exists():
        builder = MyWhooshFitBuilder(input_file)
        builder.build(output_file)
    else:
        print(f"File not found: {input_file}")