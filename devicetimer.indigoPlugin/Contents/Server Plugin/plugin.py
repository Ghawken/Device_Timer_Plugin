####################
# Copyright (c) 2025
# Bare-bones Device Timer plugin
try:
    # The indigo package is available when the plugin is started by Indigo
    import indigo
except ImportError:
    pass

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set

# Rolling windows in seconds mapped to state ids
WINDOWS: List[Tuple[str, int]] = [
    ("timeon_24hours", 24 * 3600),
    ("timeon_48hours", 48 * 3600),
    ("timeon_72hours", 72 * 3600),
    ("timeon_96hours", 96 * 3600),
    ("timeon_5days", 5 * 24 * 3600),
    ("timeon_6days", 6 * 24 * 3600),
    ("timeon_1week", 7 * 24 * 3600),
    ("timeon_2weeks", 14 * 24 * 3600),
    ("timeon_3weeks", 21 * 24 * 3600),
]

# Retention horizon to prune intervals (longest window)
RETENTION_SECONDS: int = WINDOWS[-1][1]


class Plugin(indigo.PluginBase):
    ########################################
    def __init__(
        self,
        plugin_id: str,
        plugin_display_name: str,
        plugin_version: str,
        plugin_prefs: indigo.Dict,
        **kwargs
    ) -> None:
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs, **kwargs)
        self.debug: bool = True

        # Trackers keyed by this plugin's timer device ID
        # tracker structure: {
        #   "target_id": int,
        #   "intervals": List[Tuple[datetime, Optional[datetime]]],  # [ (start, end|None) ... ]
        # }
        self.trackers: Dict[int, Dict] = {}

        # Reverse index: target device ID -> set(timer device IDs)
        self.by_target: Dict[int, Set[int]] = {}

    ########################################
    def startup(self) -> None:
        self.logger.debug("startup called -- subscribing to device changes")
        # Subscribe to changes for ALL Indigo devices (use sparingly)
        indigo.devices.subscribeToChanges()

        # Initialize trackers for any existing timer devices
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == "deviceTimer":
                self._register_tracker(dev)

    def shutdown(self) -> None:
        self.logger.debug("shutdown called")

    ########################################
    def deviceStartComm(self, dev: indigo.Device) -> None:
        # Called when a plugin device starts comms or is (re)configured
        if dev.deviceTypeId == "deviceTimer":
            self._register_tracker(dev)
            # Optional: set a timer icon
            try:
                dev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
            except Exception:
                pass

    def deviceStopComm(self, dev: indigo.Device) -> None:
        # Clean up tracker mappings when timer device stops
        if dev.deviceTypeId == "deviceTimer":
            self._unregister_tracker(dev)

    ########################################
    # Dynamic list for ConfigUI
    def all_devices(
        self,
        filter_str: str = "",
        values_dict: indigo.Dict = None,
        type_id: str = "",
        target_id: int = 0
    ) -> list:
        """
        Builds a popup list of all Indigo devices (native and plugin).
        Returns list of tuples (id_str, name).
        """
        return_list = []
        try:
            for dev_id in indigo.devices.keys():
                name = indigo.devices.getName(dev_id)
                return_list.append((str(dev_id), name))
        except Exception as exc:
            self.logger.exception(exc)
        # Sort by device name for convenience
        return sorted(return_list, key=lambda t: t[1].lower())

    ########################################
    # Subscriptions: react to any device changes
    def deviceUpdated(self, orig_dev: indigo.Device, new_dev: indigo.Device) -> None:
        super().deviceUpdated(orig_dev, new_dev)

        # If this device is being tracked, update intervals when onState changes
        timer_ids = self.by_target.get(new_dev.id, set())
        if not timer_ids:
            return

        old_on = getattr(orig_dev, "onState", None)
        new_on = getattr(new_dev, "onState", None)

        # If device doesn't support on/off, nothing to do
        if old_on is None and new_on is None:
            return

        if old_on == new_on:
            return  # No change in on/off

        now = indigo.server.getTime()
        for timer_dev_id in list(timer_ids):
            tracker = self.trackers.get(timer_dev_id)
            if not tracker:
                continue

            intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

            if new_on is True:
                # Transition to ON: start a new open interval
                if intervals and intervals[-1][1] is None:
                    # already open; ignore
                    pass
                else:
                    intervals.append((now, None))
            else:
                # Transition to OFF: close the open interval if present
                if intervals and intervals[-1][1] is None:
                    start, _ = intervals[-1]
                    intervals[-1] = (start, now)

            # After event, update the computed states immediately
            timer_dev = indigo.devices.get(timer_dev_id)
            if timer_dev:
                self._update_timer_states(timer_dev, intervals, now)

    ########################################
    def runConcurrentThread(self) -> None:
        """
        Periodically recompute rolling window totals so states remain fresh,
        even if a device stays ON for long periods.
        """
        try:
            while True:
                now = indigo.server.getTime()
                for timer_dev_id, tracker in list(self.trackers.items()):
                    timer_dev = indigo.devices.get(timer_dev_id)
                    if not timer_dev:
                        continue
                    intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

                    # Prune old intervals outside retention horizon to bound memory
                    self._prune_intervals(intervals, now)

                    # Refresh states
                    self._update_timer_states(timer_dev, intervals, now)

                # Update once per minute
                self.sleep(60)
        except self.StopThread:
            pass

    ########################################
    # Helpers
    def _register_tracker(self, timer_dev: indigo.Device) -> None:
        """Register or update a tracker for a timer device based on its config."""
        # Remove existing mapping if reconfiguring
        self._unregister_tracker(timer_dev)

        props = timer_dev.pluginProps or {}
        target_str = props.get("targetDeviceId", "")
        if not target_str:
            self.logger.warning(f"'{timer_dev.name}' has no target device selected.")
            # Initialize states to 0
            self._reset_timer_states(timer_dev)
            return

        try:
            target_id = int(target_str)
        except ValueError:
            self.logger.error(f"'{timer_dev.name}' invalid targetDeviceId: {target_str}")
            self._reset_timer_states(timer_dev)
            return

        # Create tracker structure
        now = indigo.server.getTime()
        intervals: List[Tuple[datetime, Optional[datetime]]] = []

        target_dev = indigo.devices.get(target_id)
        if target_dev:
            current_on = getattr(target_dev, "onState", None)
            if current_on:
                # Start an open interval from now
                intervals.append((now, None))
        else:
            self.logger.warning(f"'{timer_dev.name}' target device id {target_id} not found.")

        self.trackers[timer_dev.id] = {
            "target_id": target_id,
            "intervals": intervals,
        }
        self.by_target.setdefault(target_id, set()).add(timer_dev.id)

        if self.debug:
            self.logger.debug(f"Registered '{timer_dev.name}' -> target id {target_id}")

        # Initialize states
        self._update_timer_states(timer_dev, intervals, now)

    def _unregister_tracker(self, timer_dev: indigo.Device) -> None:
        """Remove tracker and reverse index entries for this timer device."""
        existing = self.trackers.pop(timer_dev.id, None)
        if existing:
            tgt = existing.get("target_id")
            if tgt in self.by_target:
                self.by_target[tgt].discard(timer_dev.id)
                if not self.by_target[tgt]:
                    del self.by_target[tgt]

    def _reset_timer_states(self, timer_dev: indigo.Device) -> None:
        kv = [{"key": key, "value": 0.0} for key, _ in WINDOWS]
        try:
            timer_dev.updateStatesOnServer(kv)
        except Exception:
            pass

    def _prune_intervals(self, intervals: List[Tuple[datetime, Optional[datetime]]], now: datetime) -> None:
        """Keep only intervals that may overlap the retention window."""
        horizon = now - timedelta(seconds=RETENTION_SECONDS)
        keep: List[Tuple[datetime, Optional[datetime]]] = []
        for start, end in intervals:
            # If interval ends before horizon, drop it
            effective_end = end or now
            if effective_end <= horizon:
                continue
            # Keep (possibly with original start; clipping is handled in computation)
            keep.append((start, end))
        if len(keep) != len(intervals):
            intervals[:] = keep

    def _compute_on_seconds(
        self,
        intervals: List[Tuple[datetime, Optional[datetime]]],
        now: datetime,
        window_seconds: int
    ) -> float:
        """Compute total ON seconds overlapping [now - window, now]."""
        window_start = now - timedelta(seconds=window_seconds)
        total = 0.0
        for start, end in intervals:
            s = start
            e = end or now
            if e <= window_start or s >= now:
                continue
            overlap_start = max(s, window_start)
            overlap_end = min(e, now)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds()
        return total

    def _update_timer_states(
        self,
        timer_dev: indigo.Device,
        intervals: List[Tuple[datetime, Optional[datetime]]],
        now: datetime
    ) -> None:
        """Recompute all states for a timer device."""
        kv_list = []
        for state_id, win_secs in WINDOWS:
            on_seconds = self._compute_on_seconds(intervals, now, win_secs)
            hours = round(on_seconds / 3600.0, 2)
            kv_list.append({"key": state_id, "value": hours})
        try:
            timer_dev.updateStatesOnServer(kv_list)
        except Exception as exc:
            self.logger.exception(exc)

    ########################################
    # Validation (optional, keep simple)
    def validateDeviceConfigUi(
        self,
        values_dict: indigo.Dict,
        type_id: str,
        dev_id: int
    ) -> tuple:
        errors: Dict[str, str] = {}
        target = values_dict.get("targetDeviceId", "")
        if not target:
            errors["targetDeviceId"] = "Please select a device to track."
        if errors:
            return (False, errors, values_dict)
        return (True, values_dict)