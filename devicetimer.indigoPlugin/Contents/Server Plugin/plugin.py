#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Device Timer plugin
try:
    import indigo
except ImportError:
    pass

import os
import sys
import platform
import traceback
import logging
import logging.handlers
from os import path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set

################################################################################
# Indigo Event Log handler that routes Python logging to Indigo's Event Log
################################################################################
class IndigoLogHandler(logging.Handler):
    def __init__(self, display_name, level=logging.NOTSET):
        super().__init__(level)
        self.displayName = display_name

    def emit(self, record):
        """not used by this class; must be called independently by indigo"""
        logmessage = ""
        is_error = False
        levelno = getattr(record, "levelno", logging.INFO)
        try:
            if self.level <= levelno:
                is_exception = record.exc_info is not None
                if levelno == 5 or levelno == logging.DEBUG:
                    logmessage = "({}:{}:{}): {}".format(path.basename(record.pathname), record.funcName, record.lineno, record.getMessage())
                elif levelno == logging.INFO:
                    logmessage = record.getMessage()
                elif levelno == logging.WARNING:
                    logmessage = record.getMessage()
                elif levelno == logging.ERROR:
                    logmessage = "({}: Function: {}  line: {}):    Error :  Message : {}".format(path.basename(record.pathname), record.funcName, record.lineno, record.getMessage())
                    is_error = True

                if is_exception:
                    logmessage = "({}: Function: {}  line: {}):    Exception :  Message : {}".format(path.basename(record.pathname), record.funcName, record.lineno, record.getMessage())
                    indigo.server.log(message=logmessage, type=self.displayName, isError=is_error, level=levelno)
                    etype, value, tb = record.exc_info
                    tb_string = "".join(traceback.format_tb(tb))
                    indigo.server.log(f"Traceback:\n{tb_string}", type=self.displayName, isError=is_error, level=levelno)
                    indigo.server.log(f"Error in plugin execution:\n\n{traceback.format_exc(30)}", type=self.displayName, isError=is_error, level=levelno)
                    indigo.server.log(f"\nExc_info: {record.exc_info} \nExc_Text: {record.exc_text} \nStack_info: {record.stack_info}", type=self.displayName, isError=is_error, level=levelno)
                    return

                indigo.server.log(message=logmessage, type=self.displayName, isError=is_error, level=levelno)
        except Exception as ex:
            indigo.server.log(f"Error in Logging: {ex}", type=self.displayName, isError=True, level=logging.ERROR)

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

RETENTION_SECONDS: int = WINDOWS[-1][1]
REFRESH_INTERVAL_SECS: int = 15


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
        # Track current local date so we can detect midnight rollovers

        try:
            self._current_date = indigo.server.getTime().date()
            self.logger.debug(f"Current date initialized to: {self._current_date}")
        except Exception:
            self._current_date = None
        # --- Logging setup ---------------------------------------------------
        # AFTER (safe)
        if hasattr(self, "indigo_log_handler") and self.indigo_log_handler:
            self.logger.removeHandler(self.indigo_log_handler)


        # Base logger level (collect everything; handlers filter)
        self.logger.setLevel(logging.DEBUG)

        # Read prefs (with safe defaults)
        try:
            self.logLevel = int(self.pluginPrefs.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(self.pluginPrefs.get("showDebugFileLevel", logging.DEBUG))
        except Exception:
            self.logLevel = logging.INFO
            self.fileloglevel = logging.DEBUG

        # Indigo Event Log handler - remove existing before adding (do NOT set to None)
        try:
            if self.indigo_log_handler:
                self.logger.removeHandler(self.indigo_log_handler)
            self.indigo_log_handler = IndigoLogHandler(plugin_display_name, self.logLevel)
            self.indigo_log_handler.setLevel(self.logLevel)
            self.indigo_log_handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(self.indigo_log_handler)
        except Exception as exc:
            indigo.server.log(f"Failed to create IndigoLogHandler: {exc}", isError=True)

        # File handler (Logs/Plugins/<bundle-id>.log)
        try:
            logs_dir = path.join(indigo.server.getInstallFolderPath(), "Logs", "Plugins")
            os.makedirs(logs_dir, exist_ok=True)
            logfile = path.join(logs_dir, f"{plugin_id}.log")
            self.plugin_file_handler = logging.handlers.RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=3)
            pfmt = logging.Formatter(
                "%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            self.plugin_file_handler.setFormatter(pfmt)
            self.plugin_file_handler.setLevel(self.fileloglevel)
            self.logger.addHandler(self.plugin_file_handler)
        except Exception as exc:
            self.logger.exception(exc)

        # Convenience debug flag
        self.debug = bool(self.pluginPrefs.get("showDebugInfo", False))

        # Session header
        self.logger.info("")
        self.logger.info("{0:=^120}".format(" Initializing Device Timer "))
        self.logger.info(f"{'Plugin name:':<28} {plugin_display_name}")
        self.logger.info(f"{'Plugin version:':<28} {plugin_version}")
        self.logger.info(f"{'Plugin ID:':<28} {plugin_id}")
        self.logger.info(f"{'Indigo version:':<28} {indigo.server.version}")
        self.logger.info(f"{'Silicon version:':<28} {platform.machine()}")
        self.logger.info(f"{'Python version:':<28} {sys.version.replace(os.linesep, ' ')}")
        self.logger.info(f"{'Python Directory:':<28} {sys.prefix.replace(os.linesep, ' ')}")

        # --- Plugin runtime state -------------------------------------------
        # Trackers keyed by this plugin's timer device ID
        # tracker structure: {
        #   "target_id": int,
        #   "intervals": List[Tuple[datetime, Optional[datetime]]],
        #   "offsets": Dict[state_id, float],  # hours snapshot at startup to preserve displayed values
        # }
        self.trackers: Dict[int, Dict] = {}
        self.by_target: Dict[int, Set[int]] = {}


        self.logger.info("{0:=^120}".format(" End Initializing Device Timer "))

    ########################################
    def startup(self) -> None:
        self.logger.debug("startup called -- subscribing to device changes")
        try:
            indigo.devices.subscribeToChanges()
        except Exception as exc:
            self.logger.exception(exc)

        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == "deviceTimer":
                self._register_tracker(dev)

    def shutdown(self) -> None:
        self.logger.debug("shutdown called")

    ########################################
    def closedPrefsConfigUi(self, values_dict: indigo.Dict, user_cancelled: bool) -> None:

        self.logger.debug(f"closedPluginConfigUi called with values_dict: {values_dict} and user_cancelled: {user_cancelled}")
        if user_cancelled:
            return
        # Persist and apply log settings
        try:
            self.pluginPrefs["showDebugInfo"] = bool(values_dict.get("showDebugInfo", False))
            self.pluginPrefs["showDebugLevel"] = int(values_dict.get("showDebugLevel", logging.INFO))
            self.pluginPrefs["showDebugFileLevel"] = int(values_dict.get("showDebugFileLevel", logging.DEBUG))
            indigo.server.savePluginPrefs()

            self.debug = bool(values_dict.get("showDebugInfo", False))
            self.logLevel = int(values_dict.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(values_dict.get("showDebugFileLevel", logging.DEBUG))

            self.logLevel = int(values_dict.get("showDebugLevel", '5'))
            self.fileloglevel = int(values_dict.get("showDebugFileLevel", '5'))
            self.debug1 = values_dict.get('debug1', False)
            self.debug2 = values_dict.get('debug2', False)
            self.debug3 = values_dict.get('debug3', False)
            self.debug4 = values_dict.get('debug4', False)
            self.debug5 = values_dict.get('debug5', False)
            self.debug6 = values_dict.get('debug6', False)
            self.debug7 = values_dict.get('debug7', False)
            self.debug8 = values_dict.get('debug8', False)
            self.debug9 = values_dict.get('debug9', False)

            self.indigo_log_handler.setLevel(self.logLevel)
            self.plugin_file_handler.setLevel(self.fileloglevel)

            self.logger.debug(u"logLevel = " + str(self.logLevel))
            self.logger.debug(u"User prefs saved.")
            self.logger.debug(u"Debugging on (Level: {0})".format(self.logLevel))


            self.logger.info(f"Applied logging prefs: EventLog={logging.getLevelName(self.logLevel)}, File={logging.getLevelName(self.fileloglevel)}, Debug={'on' if self.debug else 'off'}")
        except Exception as exc:
            self.logger.exception(exc)

    ########################################
    def deviceStartComm(self, dev: indigo.Device) -> None:
        if dev.deviceTypeId == "deviceTimer":
            self._register_tracker(dev)
            dev.stateListOrDisplayStateIdChanged()
            try:
                dev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
            except Exception:
                pass

    def deviceStopComm(self, dev: indigo.Device) -> None:
        if dev.deviceTypeId == "deviceTimer":
            self._unregister_tracker(dev)

    # ADD
    def _compute_on_seconds_between(
            self,
            intervals: List[Tuple[datetime, Optional[datetime]]],
            start_ts: datetime,
            end_ts: datetime
    ) -> float:
        total = 0.0
        for s, e in intervals:
            s0 = s
            e0 = e or end_ts
            if e0 <= start_ts or s0 >= end_ts:
                continue
            overlap_start = max(s0, start_ts)
            overlap_end = min(e0, end_ts)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds()
        return total

    # ADD
    def _format_duration_text(self, total_seconds: float) -> str:
        secs = int(round(total_seconds))
        hours = secs // 3600
        mins = (secs % 3600) // 60
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
        if mins > 0 or hours == 0:
            parts.append(f"{mins} min" + ("s" if mins != 1 else ""))
        return " and ".join(parts)
    ########################################
    def all_devices(
        self,
        filter_str: str = "",
        values_dict: indigo.Dict = None,
        type_id: str = "",
        target_id: int = 0
    ) -> list:
        return_list = []
        try:
            for dev_id in indigo.devices.keys():
                name = indigo.devices.getName(dev_id)
                return_list.append((str(dev_id), name))
        except Exception as exc:
            self.logger.exception(exc)
        return sorted(return_list, key=lambda t: t[1].lower())

    ########################################
    def deviceUpdated(self, orig_dev: indigo.Device, new_dev: indigo.Device) -> None:
        super().deviceUpdated(orig_dev, new_dev)

        timer_ids = self.by_target.get(new_dev.id, set())
        if not timer_ids:
            return

        self.logger.debug(f"deviceUpdated: target '{new_dev.name}' ({new_dev.id}) has {len(timer_ids)} timer(s) tracking it")

        # Always refresh metadata on any update
        for timer_dev_id in list(timer_ids):
            timer_dev = indigo.devices.get(timer_dev_id)
            if timer_dev:
                self._update_target_meta_states(timer_dev, new_dev)

        old_on = getattr(orig_dev, "onState", None)
        new_on = getattr(new_dev, "onState", None)


        if old_on is not None or new_on is not None:
            if old_on != new_on:
                self.logger.debug(f"Tracked device change: '{new_dev.name}' (id {new_dev.id}) onState {old_on} -> {new_on}")

        # If device doesn't support on/off or no transition, stop here
        if (old_on is None and new_on is None) or (old_on == new_on):
            return

        now = indigo.server.getTime()
        for timer_dev_id in list(timer_ids):
            tracker = self.trackers.get(timer_dev_id)
            if not tracker:
                continue

            intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

            if new_on is True:
                if not (intervals and intervals[-1][1] is None):
                    intervals.append((now, None))
                    # Record an ON event timestamp for counting
                tracker.setdefault("on_events", []).append(now)
                td = indigo.devices.get(timer_dev_id)
                tname = td.name if td else f"id {timer_dev_id}"
                self.logger.debug(f"Recorded ON event for '{tname}' at {now}")
            else:
                if intervals and intervals[-1][1] is None:
                    start, _ = intervals[-1]
                    intervals[-1] = (start, now)

            timer_dev = indigo.devices.get(timer_dev_id)
            if timer_dev:
                self._update_timer_states(timer_dev, tracker, now)

    ########################################
    # Function: runConcurrentThread (midnight block only, around L190-L245)
    # - Log final yesterday totals and roll baselines so that 'yesterday' remains correct post-rollover
    #   and 'today' restarts at 0. Also keep oncount baselines.
    def runConcurrentThread(self) -> None:
        try:
            while True:
                now = indigo.server.getTime()

                # Midnight rollover detection and logging
                try:
                    if getattr(self, "_current_date", None) is None:
                        self._current_date = now.date()
                    elif now.date() != self._current_date:
                        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                        yday_start = today_start - timedelta(days=1)
                        self.logger.info(f"Midnight rollover: {self._current_date} -> {now.date()}")
                        for timer_dev_id, tracker in list(self.trackers.items()):
                            timer_dev = indigo.devices.get(timer_dev_id)
                            if not timer_dev:
                                continue
                            intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

                            # Finished day totals (minutes) = interval sum for yday + baseline 'today'
                            seconds_finished_day = self._compute_on_seconds_between(intervals, yday_start, today_start)
                            minutes_finished_day_since = round(seconds_finished_day / 60.0, 1)
                            minutes_finished_day_total = round(
                                minutes_finished_day_since + float(tracker.get("day_offsets", {}).get("today", 0.0)), 1)

                            # Finished day ON event counts = observed in yday + baseline 'today'
                            on_events = tracker.get("on_events", [])
                            yday_count_since = sum(1 for t in on_events if yday_start <= t < today_start)
                            yday_count_total = int(
                                yday_count_since + int(tracker.get("count_offsets", {}).get("today", 0)))

                            self.logger.info(
                                f"Yesterday total for '{timer_dev.name}': {minutes_finished_day_total:.1f} min; "
                                f"On events: {yday_count_total}; Today starts at 0.0"
                            )

                            # Roll baselines: yesterday becomes finished day, reset today's baselines
                            tracker["day_offsets"] = {"today": 0.0, "yesterday": minutes_finished_day_total}
                            tracker["count_offsets"] = {"today": 0, "yesterday": yday_count_total}
                             # Lock yesterday for the new day so we don't add interval-based 'since' again
                            tracker["yesterday_locked_for_date"] = now.date()
                        self._current_date = now.date()
                except Exception as exc:
                    self.logger.exception(exc)

                for timer_dev_id, tracker in list(self.trackers.items()):
                    timer_dev = indigo.devices.get(timer_dev_id)
                    if not timer_dev:
                        continue

                    intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

                    # Prune old intervals
                    self._prune_intervals(intervals, now)
                    # Prune old ON event timestamps (keep only yesterday/today)
                    self._prune_on_events(tracker.setdefault("on_events", []), now)

                    # Refresh target metadata frequently
                    target_id = tracker.get("target_id")
                    target_dev = indigo.devices.get(target_id) if target_id is not None else None
                    if target_dev:
                        self._update_target_meta_states(timer_dev, target_dev)
                        current_on = getattr(target_dev, "onState", None)
                        if current_on and not (intervals and intervals[-1][1] is None):
                            intervals.append((now, None))
                            self.logger.debug(f"Opened interval for timer '{timer_dev.name}' due to target ON")

                    # Keep timers live
                    self._update_timer_states(timer_dev, tracker, now)

                self.sleep(REFRESH_INTERVAL_SECS)
        except self.StopThread:
            pass

    ########################################
    # Helpers
    # Function: _register_tracker (around L300-L370)
    # - Read current device states for today/yesterday minutes and counts into baselines at startup.
    def _register_tracker(self, timer_dev: indigo.Device) -> None:
        self._unregister_tracker(timer_dev)

        props = timer_dev.pluginProps or {}
        target_str = props.get("targetDeviceId", "")
        if not target_str:
            self.logger.warning(f"'{timer_dev.name}' has no target device selected.")
            self._update_target_meta_states(timer_dev, None)
            self.trackers[timer_dev.id] = {
                "target_id": None,
                "intervals": [],
                "offsets": {},
                "day_offsets": {"today": 0.0, "yesterday": 0.0},
                "count_offsets": {"today": 0, "yesterday": 0},
                "on_events": [],
                "yesterday_locked_for_date": indigo.server.getTime().date(),
            }
            return

        try:
            target_id = int(target_str)
        except ValueError:
            self.logger.error(f"'{timer_dev.name}' invalid targetDeviceId: {target_str}")
            self._update_target_meta_states(timer_dev, None)
            self.trackers[timer_dev.id] = {
                "target_id": None,
                "intervals": [],
                "offsets": {},
                "day_offsets": {"today": 0.0, "yesterday": 0.0},
                "count_offsets": {"today": 0, "yesterday": 0},
                "on_events": [],
            }
            return

        now = indigo.server.getTime()
        intervals: List[Tuple[datetime, Optional[datetime]]] = []

        target_dev = indigo.devices.get(target_id)
        if target_dev:
            current_on = getattr(target_dev, "onState", None)
            if current_on:
                intervals.append((now, None))
                self.logger.debug(f"Opened interval at startup for '{timer_dev.name}' (target ON)")
        else:
            self.logger.warning(f"'{timer_dev.name}' target device id {target_id} not found.")

        # Baselines for rolling windows (minutes)
        offsets: Dict[str, float] = {}
        try:
            for state_id, _ in WINDOWS:
                v = timer_dev.states.get(state_id, 0)
                try:
                    offsets[state_id] = float(v)
                except Exception:
                    offsets[state_id] = 0.0
            self.logger.debug(
                f"Captured rolling offsets for '{timer_dev.name}': " +
                ", ".join([f"{k}={offsets[k]:.1f}" for k, _ in WINDOWS])
            )
        except Exception as exc:
            self.logger.exception(exc)

        # Baselines for day-bounded minutes (today/yesterday)
        day_offsets = {"today": 0.0, "yesterday": 0.0}
        try:
            t_today = timer_dev.states.get("timeon_today", 0)
            t_yday = timer_dev.states.get("timeon_yesterday", 0)
            day_offsets["today"] = float(t_today) if t_today is not None else 0.0
            day_offsets["yesterday"] = float(t_yday) if t_yday is not None else 0.0
            self.logger.debug(
                f"Captured day offsets for '{timer_dev.name}': today={day_offsets['today']:.1f} min, "
                f"yesterday={day_offsets['yesterday']:.1f} min"
            )
        except Exception as exc:
            self.logger.exception(exc)

        # Baselines for on-event counts (today/yesterday)
        count_offsets = {"today": 0, "yesterday": 0}
        try:
            c_today = timer_dev.states.get("oncount_today", 0)
            c_yday = timer_dev.states.get("oncount_yesterday", 0)
            count_offsets["today"] = int(c_today) if c_today is not None else 0
            count_offsets["yesterday"] = int(c_yday) if c_yday is not None else 0
            self.logger.debug(
                f"Captured count offsets for '{timer_dev.name}': today={count_offsets['today']}, "
                f"yesterday={count_offsets['yesterday']}"
            )
        except Exception as exc:
            self.logger.exception(exc)

        self.trackers[timer_dev.id] = {
            "target_id": target_id,  # or None in the no-target branch
            "intervals": intervals,
            "offsets": offsets,
            "day_offsets": day_offsets,
            "count_offsets": count_offsets,
            "on_events": [],
            "yesterday_locked_for_date": indigo.server.getTime().date(),  # lock for the current date
        }
        self.by_target.setdefault(target_id, set()).add(timer_dev.id)
        self.logger.debug(f"Registered '{timer_dev.name}' -> target id {target_id} (intervals: {len(intervals)})")
        self._update_target_meta_states(timer_dev, target_dev)

    def _unregister_tracker(self, timer_dev: indigo.Device) -> None:
        existing = self.trackers.pop(timer_dev.id, None)
        if existing:
            tgt = existing.get("target_id")
            if tgt in self.by_target:
                self.by_target[tgt].discard(timer_dev.id)
                if not self.by_target[tgt]:
                    del self.by_target[tgt]

    def _reset_timer_states(self, timer_dev: indigo.Device) -> None:
        kv = [{"key": key, "value": 0.0, "uiValue": "0.0", "decimalPlaces": 1} for key, _ in WINDOWS]
        kv.extend([
            {"key": "target_device_id", "value": 0},
            {"key": "target_device_name", "value": "--"},
            {"key": "target_on_state", "value": False},
        ])
        try:
            timer_dev.updateStatesOnServer(kv)
        except Exception:
            pass

    # Add this helper alongside _prune_intervals()
    def _prune_on_events(self, events: List[datetime], now: datetime) -> None:
        """
        Keep only ON event timestamps from yesterday midnight forward, since we only
        need to compute counts for 'yesterday' and 'today'.
        """
        try:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yday_start = today_start - timedelta(days=1)
            cutoff = yday_start
            if events:
                events[:] = [t for t in events if t >= cutoff]
        except Exception as exc:
            self.logger.exception(exc)

    def _prune_intervals(self, intervals: List[Tuple[datetime, Optional[datetime]]], now: datetime) -> None:
        horizon = now - timedelta(seconds=RETENTION_SECONDS)
        keep: List[Tuple[datetime, Optional[datetime]]] = []
        for start, end in intervals:
            effective_end = end or now
            if effective_end <= horizon:
                continue
            keep.append((start, end))
        if len(keep) != len(intervals):
            intervals[:] = keep

    def _compute_on_seconds(
        self,
        intervals: List[Tuple[datetime, Optional[datetime]]],
        now: datetime,
        window_seconds: int
    ) -> float:
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

    # CHANGE: replace _update_timer_states with offset-aware version
    # REPLACE
    # Function: _update_timer_states (around L520-L610)
    # - Add baselines to today/yesterday minutes and counts.
    def _update_timer_states(
            self,
            timer_dev: indigo.Device,
            tracker: Dict,
            now: datetime
    ) -> None:
        """
        Publish rolling window states in minutes (1dp), their text variants,
        and today/yesterday (midnight-anchored). Rolling windows use startup
        offsets; day totals and counts use their own startup baselines.
        """
        intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]
        offsets: Dict[str, float] = tracker.get("offsets", {})
        day_offsets: Dict[str, float] = tracker.get("day_offsets", {"today": 0.0, "yesterday": 0.0})
        count_offsets: Dict[str, int] = tracker.get("count_offsets", {"today": 0, "yesterday": 0})

        kv_list = []

        # Rolling windows (minutes + text)
        for state_id, win_secs in WINDOWS:
            on_seconds = self._compute_on_seconds(intervals, now, win_secs)
            minutes_since_start = round(on_seconds / 60.0, 1)
            total_minutes = round(minutes_since_start + float(offsets.get(state_id, 0.0)), 1)
            kv_list.append(
                {"key": state_id, "value": total_minutes, "uiValue": f"{total_minutes:.1f}", "decimalPlaces": 1})
            kv_list.append({"key": f"{state_id}_text", "value": self._format_duration_text(total_minutes * 60.0)})

        # Day-bounded totals
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yday_start = today_start - timedelta(days=1)

        seconds_today = self._compute_on_seconds_between(intervals, today_start, now)
        minutes_today = round(seconds_today / 60.0, 1)
        minutes_today_total = round(minutes_today + float(day_offsets.get("today", 0.0)), 1)
        kv_list.append({"key": "timeon_today", "value": minutes_today_total, "uiValue": f"{minutes_today_total:.1f}",
                        "decimalPlaces": 1})
        kv_list.append({"key": "timeon_today_text", "value": self._format_duration_text(minutes_today_total * 60.0)})

        # Today OFF (derived from elapsed day - on)
        elapsed_today_minutes = round((now - today_start).total_seconds() / 60.0, 1)
        off_today_minutes = max(0.0, round(elapsed_today_minutes - minutes_today_total, 1))
        kv_list.append({"key": "timeoff_today", "value": off_today_minutes, "uiValue": f"{off_today_minutes:.1f}",
                        "decimalPlaces": 1})
        kv_list.append({"key": "timeoff_today_text", "value": self._format_duration_text(off_today_minutes * 60.0)})
        # Yesterday ON (minutes + text)
        seconds_yday = self._compute_on_seconds_between(intervals, yday_start, today_start)
        minutes_yday = round(seconds_yday / 60.0, 1)
        y_locked_date = tracker.get("yesterday_locked_for_date")
        if y_locked_date == now.date():
            minutes_yday_total = float(day_offsets.get("yesterday", 0.0))
        else:
            minutes_yday_total = round(minutes_yday + float(day_offsets.get("yesterday", 0.0)), 1)

        kv_list.append({"key": "timeon_yesterday", "value": minutes_yday_total, "uiValue": f"{minutes_yday_total:.1f}",
                        "decimalPlaces": 1})
        kv_list.append({"key": "timeon_yesterday_text", "value": self._format_duration_text(minutes_yday_total * 60.0)})

        # Yesterday OFF (24h - on)
        full_day_minutes = 24 * 60.0
        off_yday_minutes = max(0.0, round(full_day_minutes - minutes_yday_total, 1))
        kv_list.append({"key": "timeoff_yesterday", "value": off_yday_minutes, "uiValue": f"{off_yday_minutes:.1f}",
                        "decimalPlaces": 1})
        kv_list.append({"key": "timeoff_yesterday_text", "value": self._format_duration_text(off_yday_minutes * 60.0)})

        # On-event counts
        on_events = tracker.get("on_events", [])
        count_today = sum(1 for t in on_events if today_start <= t < now)
        count_yday = sum(1 for t in on_events if yday_start <= t < today_start)

        count_today_total = int(count_today + int(count_offsets.get("today", 0)))

        yday_count_since = sum(1 for t in on_events if yday_start <= t < today_start)
        if y_locked_date == now.date():
            count_yday_total = int(count_offsets.get("yesterday", 0))
        else:
            count_yday_total = int(yday_count_since + int(count_offsets.get("yesterday", 0)))
        kv_list.append({"key": "oncount_yesterday", "value": count_yday_total, "uiValue": str(count_yday_total)})
        kv_list.append({"key": "oncount_today", "value": count_today_total, "uiValue": str(count_today_total)})

        try:
            timer_dev.updateStatesOnServer(kv_list)
            self.logger.debug(
                f"Updated timers (minutes) for '{timer_dev.name}': " +
                ", ".join([f"{kv['key']}={kv.get('uiValue', kv.get('value'))}" for kv in kv_list if
                           kv['key'].startswith('timeon_') and not kv['key'].endswith('_text')])
            )
        except Exception as exc:
            self.logger.exception(exc)

    def _update_target_meta_states(self, timer_dev: indigo.Device, target_dev: Optional[indigo.Device]) -> None:
        if target_dev:
            on_val = getattr(target_dev, "onState", False)
            kv = [
                {"key": "target_device_id", "value": int(target_dev.id)},
                {"key": "target_device_name", "value": target_dev.name},
                {"key": "target_on_state", "value": bool(on_val) if on_val is not None else False},
            ]
        else:
            kv = [
                {"key": "target_device_id", "value": 0},
                {"key": "target_device_name", "value": "--"},
                {"key": "target_on_state", "value": False},
            ]
        try:
            timer_dev.updateStatesOnServer(kv)
            self.logger.debug(f"Meta updated for '{timer_dev.name}': " + ", ".join([f"{d['key']}={d['value']}" for d in kv]))
        except Exception as exc:
            self.logger.exception(exc)

    ########################################
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