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

        # --- Logging setup ---------------------------------------------------
        self.indigo_log_handler: Optional[IndigoLogHandler] = None
        self.plugin_file_handler: Optional[logging.Handler] = None

        # Base logger level (collect everything; handlers filter)
        self.logger.setLevel(logging.DEBUG)

        # Read prefs (with safe defaults)
        try:
            self.logLevel = int(self.pluginPrefs.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(self.pluginPrefs.get("showDebugFileLevel", logging.DEBUG))
        except Exception:
            self.logLevel = logging.INFO
            self.fileloglevel = logging.DEBUG

        # Indigo Event Log handler
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
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s',
                                 datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        self.debug = self.pluginPrefs.get('showDebugInfo', False)
        self.debug1 = self.pluginPrefs.get('debug1', False)
        self.debug2 = self.pluginPrefs.get('debug2', False)
        self.debug3 = self.pluginPrefs.get('debug3', False)
        self.debug4 = self.pluginPrefs.get('debug4',False)
        self.debug5 = self.pluginPrefs.get('debug5', False)
        self.debug6 = self.pluginPrefs.get('debug6', False)
        self.debug7 = self.pluginPrefs.get('debug7', False)
        self.debug8 = self.pluginPrefs.get('debug8', False)
        self.indigo_log_handler.setLevel(self.logLevel)
        self.plugin_file_handler.setLevel(self.fileloglevel)

        # Convenience debug flags (optional fine-grained toggles)
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
        #   "preserve": bool,  # preserve states after restart until first on/off transition
        # }
        self.trackers: Dict[int, Dict] = {}
        self.by_target: Dict[int, Set[int]] = {}


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
    def closedPluginConfigUi(self, values_dict: indigo.Dict, user_cancelled: bool) -> None:
        if user_cancelled:
            return
        # Persist and apply log settings
        try:
            self.pluginPrefs["showDebugInfo"] = bool(values_dict.get("showDebugInfo", False))
            self.pluginPrefs["showDebugLevel"] = int(values_dict.get("showDebugLevel", logging.INFO))
            self.pluginPrefs["showDebugFileLevel"] = int(values_dict.get("showDebugFileLevel", logging.DEBUG))
            indigo.server.savePluginPrefs()

            self.debug = bool(self.pluginPrefs.get("showDebugInfo", False))
            self.logLevel = int(self.pluginPrefs.get("showDebugLevel", logging.INFO))
            self.fileloglevel = int(self.pluginPrefs.get("showDebugFileLevel", logging.DEBUG))

            if self.indigo_log_handler:
                self.indigo_log_handler.setLevel(self.logLevel)
            if self.plugin_file_handler:
                self.plugin_file_handler.setLevel(self.fileloglevel)

            self.logger.info(f"Applied logging prefs: EventLog={logging.getLevelName(self.logLevel)}, File={logging.getLevelName(self.fileloglevel)}, Debug={'on' if self.debug else 'off'}")
        except Exception as exc:
            self.logger.exception(exc)

    ########################################
    def deviceStartComm(self, dev: indigo.Device) -> None:
        if dev.deviceTypeId == "deviceTimer":
            self._register_tracker(dev)
            try:
                dev.updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
            except Exception:
                pass

    def deviceStopComm(self, dev: indigo.Device) -> None:
        if dev.deviceTypeId == "deviceTimer":
            self._unregister_tracker(dev)

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
                self.logger.info(f"Tracked device change: '{new_dev.name}' (id {new_dev.id}) onState {old_on} -> {new_on}")

        # If device doesn't support on/off or no transition, stop here
        if (old_on is None and new_on is None) or (old_on == new_on):
            return

        now = indigo.server.getTime()
        for timer_dev_id in list(timer_ids):
            tracker = self.trackers.get(timer_dev_id)
            if not tracker:
                continue

            intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

            # Exit preserve mode on first transition
            if tracker.get("preserve", False):
                tracker["preserve"] = False
                self.logger.debug(f"Preserve mode off for timer device id {timer_dev_id} (first transition seen)")

            if new_on is True:
                if not (intervals and intervals[-1][1] is None):
                    intervals.append((now, None))
            else:
                if intervals and intervals[-1][1] is None:
                    start, _ = intervals[-1]
                    intervals[-1] = (start, now)

            timer_dev = indigo.devices.get(timer_dev_id)
            if timer_dev and not tracker.get("preserve", False):
                self._update_timer_states(timer_dev, intervals, now)

    ########################################
    def runConcurrentThread(self) -> None:
        try:
            while True:
                now = indigo.server.getTime()
                for timer_dev_id, tracker in list(self.trackers.items()):
                    timer_dev = indigo.devices.get(timer_dev_id)
                    if not timer_dev:
                        continue

                    intervals: List[Tuple[datetime, Optional[datetime]]] = tracker["intervals"]

                    self._prune_intervals(intervals, now)

                    target_id = tracker.get("target_id")
                    target_dev = indigo.devices.get(target_id) if target_id is not None else None
                    if target_dev:
                        self._update_target_meta_states(timer_dev, target_dev)

                        current_on = getattr(target_dev, "onState", None)
                        if current_on and not (intervals and intervals[-1][1] is None):
                            intervals.append((now, None))
                            self.logger.debug(f"Opened interval for timer '{timer_dev.name}' due to target ON")

                    if not tracker.get("preserve", False):
                        self._update_timer_states(timer_dev, intervals, now)
                    else:
                        self.logger.debug(f"Preserving existing timer states for '{timer_dev.name}' (awaiting first on/off change)")

                self.sleep(REFRESH_INTERVAL_SECS)
        except self.StopThread:
            pass

    ########################################
    # Helpers
    def _register_tracker(self, timer_dev: indigo.Device) -> None:
        self._unregister_tracker(timer_dev)

        props = timer_dev.pluginProps or {}
        target_str = props.get("targetDeviceId", "")
        if not target_str:
            self.logger.warning(f"'{timer_dev.name}' has no target device selected.")
            self._update_target_meta_states(timer_dev, None)
            self.trackers[timer_dev.id] = {"target_id": None, "intervals": [], "preserve": True}
            return

        try:
            target_id = int(target_str)
        except ValueError:
            self.logger.error(f"'{timer_dev.name}' invalid targetDeviceId: {target_str}")
            self._update_target_meta_states(timer_dev, None)
            self.trackers[timer_dev.id] = {"target_id": None, "intervals": [], "preserve": True}
            return

        now = indigo.server.getTime()
        intervals: List[Tuple[datetime, Optional[datetime]]] = []
        target_dev = indigo.devices.get(target_id)
        if target_dev:
            current_on = getattr(target_dev, "onState", None)
            if current_on:
                intervals.append((now, None))
        else:
            self.logger.warning(f"'{timer_dev.name}' target device id {target_id} not found.")

        self.trackers[timer_dev.id] = {
            "target_id": target_id,
            "intervals": intervals,
            "preserve": True,
        }
        self.by_target.setdefault(target_id, set()).add(timer_dev.id)

        self.logger.debug(f"Registered '{timer_dev.name}' -> target id {target_id} (preserve mode on)")
        self._update_target_meta_states(timer_dev, target_dev)

    def _unregister_tracker(self, timer_dev: indigo.Device) -> None:
        existing = self.trackers.pop(timer_dev.id, None)
        if existing:
            tgt = existing.get("target_id")
            if tgt in self.by_target:
                self.by_target[tgt].discard(timer_dev.id)
                if not self.by_target[tgt]:
                    del self.by_target[tgt]

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

    def _update_timer_states(
        self,
        timer_dev: indigo.Device,
        intervals: List[Tuple[datetime, Optional[datetime]]],
        now: datetime
    ) -> None:
        kv_list = []
        for state_id, win_secs in WINDOWS:
            on_seconds = self._compute_on_seconds(intervals, now, win_secs)
            hours = round(on_seconds / 3600.0, 2)
            kv_list.append({
                "key": state_id,
                "value": hours,
                "uiValue": f"{hours:.2f}",
                "decimalPlaces": 2
            })
        try:
            timer_dev.updateStatesOnServer(kv_list)
            self.logger.debug(f"Updated timers for '{timer_dev.name}': " + ", ".join([f"{kv['key']}={kv['uiValue']}" for kv in kv_list]))
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