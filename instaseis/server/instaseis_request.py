#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Base Instaseis Request handler currently only settings default headers.

:copyright:
    Lion Krischer (krischer@geophysik.uni-muenchen.de), 2015
:license:
    GNU Lesser General Public License, Version 3 [non-commercial/academic use]
    (http://www.gnu.org/copyleft/lgpl.html)
"""
from abc import abstractmethod
import obspy
import tornado
from ..base_instaseis_db import _get_seismogram_times

from .. import __version__


class InstaseisRequestHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Server", "InstaseisServer/%s" % __version__)


class InstaseisTimeSeriesHandler(InstaseisRequestHandler):
    arguments = None
    connection_closed = False

    def __init__(self, *args, **kwargs):
        super(InstaseisTimeSeriesHandler, self).__init__(*args, **kwargs)

    def on_connection_close(self):
        """
        Called when the client cancels the connection. Then the loop
        requesting seismograms will stop.
        """
        InstaseisRequestHandler.on_connection_close(self)
        self.__connection_closed = True

    def parse_arguments(self):
        # Make sure that no additional arguments are passed.
        unknown_arguments = set(self.request.arguments.keys()).difference(set(
            self.arguments.keys()))
        if unknown_arguments:
            msg = "The following unknown parameters have been passed: %s" % (
                ", ".join("'%s'" % _i for _i in sorted(unknown_arguments)))
            raise tornado.web.HTTPError(400, log_message=msg,
                                        reason=msg)

        # Check for duplicates.
        duplicates = []
        for key, value in self.request.arguments.items():
            if len(value) == 1:
                continue
            else:
                duplicates.append(key)
        if duplicates:
            msg = "Duplicate parameters: %s" % (
                ", ".join("'%s'" % _i for _i in sorted(duplicates)))
            raise tornado.web.HTTPError(400, log_message=msg,
                                        reason=msg)

        args = obspy.core.AttribDict()
        for name, properties in self.arguments.items():
            if "required" in properties:
                try:
                    value = self.get_argument(name)
                except:
                    msg = "Required parameter '%s' not given." % name
                    raise tornado.web.HTTPError(400, log_message=msg,
                                                reason=msg)
            else:
                if "default" in properties:
                    default = properties["default"]
                else:
                    default = None
                value = self.get_argument(name, default=default)
            if value is not None:
                try:
                    value = properties["type"](value)
                except:
                    if "format" in properties:
                        msg = "Parameter '%s' must be formatted as: '%s'" % (
                            name, properties["format"])
                    else:
                        msg = ("Parameter '%s' could not be converted to "
                               "'%s'.") % (
                            name, str(properties["type"].__name__))
                    raise tornado.web.HTTPError(400, log_message=msg,
                                                reason=msg)
            setattr(args, name, value)

        # Validate some of them right here.
        self.validate_parameters(args)

        return args

    @abstractmethod
    def validate_parameters(self, args):
        pass

    def parse_time_settings(self, args):
        """
        Attempt to figure out the time settings.

        This is pretty messy unfortunately. After this method has been
        called, args.origintime will always be set to an absolute time.

        args.starttime and args.endtime will either be set to absolute times
        or dictionaries describing phase relative offsets.

        Returns the minium possible start- and the maximum possible endtime.
        """
        if args.origintime is None:
            args.origintime = obspy.UTCDateTime(0)

        # The origin time will be always set. If the starttime is not set,
        # set it to the origin time.
        if args.starttime is None:
            args.starttime = args.origintime

        # Now it becomes a bit ugly. If the starttime is a float, treat it
        # relative to the origin time.
        if isinstance(args.starttime, float):
            args.starttime = args.origintime + args.starttime

        # Now deal with the endtime.
        if isinstance(args.endtime, float):
            # If the start time is already known as an absolute time,
            # just add it.
            if isinstance(args.starttime, obspy.UTCDateTime):
                args.endtime = args.starttime + args.endtime
            # Otherwise the start time has to be a phase relative time and
            # is dealt with later.
            else:
                assert isinstance(args.starttime, obspy.core.AttribDict)

        # Figure out the maximum temporal range of the seismograms.
        ti = _get_seismogram_times(
            info=self.application.db.info, origin_time=args.origintime,
            dt=args.dt, kernelwidth=args.kernelwidth,
            remove_source_shift=False, reconvolve_stf=False)

        # If the endtime is not set, do it here.
        if args.endtime is None:
            args.endtime = ti["endtime"]

        # Do a couple of sanity checks here.
        if isinstance(args.starttime, obspy.UTCDateTime):
            # The desired seismogram start time must be before the end time of
            # the seismograms.
            if args.starttime >= ti["endtime"]:
                msg = ("The `starttime` must be before the seismogram ends.")
                raise tornado.web.HTTPError(400, log_message=msg, reason=msg)
            # Arbitrary limit: The starttime can be at max one hour before the
            # origin time.
            if args.starttime < (ti["starttime"] - 3600):
                msg = ("The seismogram can start at the maximum one hour "
                       "before the origin time.")
                raise tornado.web.HTTPError(400, log_message=msg, reason=msg)

        if isinstance(args.endtime, obspy.UTCDateTime):
            # The endtime must be within the seismogram window
            if not (ti["starttime"] <= args.endtime <= ti["endtime"]):
                msg = ("The end time of the seismograms lies outside the "
                       "allowed range.")
                raise tornado.web.HTTPError(400, log_message=msg, reason=msg)

        return ti["starttime"], ti["endtime"]

    def set_headers(self, default_label, args):
        if args.format == "miniseed":
            content_type = "application/octet-stream"
        elif args.format == "saczip":
            content_type = "application/zip"
        self.set_header("Content-Type", content_type)

        FILE_ENDINGS_MAP = {
            "miniseed": "mseed",
            "saczip": "zip"}

        if args.label:
            label = args.label
        else:
            label = default_label

        filename = "%s_%s.%s" % (
            label,
            str(obspy.UTCDateTime()).replace(":", "_"),
            FILE_ENDINGS_MAP[args.format])

        self.set_header("Content-Disposition",
                        "attachment; filename=%s" % filename)

    def get_ttime(self, source, receiver, phase):
        if self.application.travel_time_callback is None:
            msg = "Server does not support travel time calculations."
            raise tornado.web.HTTPError(
                404, log_message=msg, reason=msg)
        try:
            tt = self.application.travel_time_callback(
                sourcelatitude=source.latitude,
                sourcelongitude=source.longitude,
                sourcedepthinmeters=source.depth_in_m,
                receiverlatitude=receiver.latitude,
                receiverlongitude=receiver.longitude,
                receiverdepthinmeters=receiver.depth_in_m,
                phase_name=phase)
        except ValueError as e:
            err_msg = str(e)
            if err_msg.lower().startswith("invalid phase name"):
                msg = "Invalid phase name: %s" % phase
            else:
                msg = "Failed to calculate travel time due to: %s" % err_msg
            raise tornado.web.HTTPError(400, log_message=msg, reason=msg)
        return tt

    def validate_geometry(self, source, receiver):
        """
        Validate the source-receiver geometry.
        """
        info = self.application.db.info

        # XXX: Will have to be changed once we have a database recorded for
        # example on the ocean bottom.
        if info.is_reciprocal:
            # Receiver must be at the surface.
            if receiver.depth_in_m is not None:
                if receiver.depth_in_m != 0.0:
                    msg = "Receiver must be at the surface for reciprocal " \
                          "databases."
                    raise tornado.web.HTTPError(400, log_message=msg,
                                                reason=msg)
            # Source depth must be within the allowed range.
            if not ((info.planet_radius - info.max_radius) <=
                    source.depth_in_m <=
                    (info.planet_radius - info.min_radius)):
                msg = ("Source depth must be within the database range: %.1f "
                       "- %.1f meters.") % (
                        info.planet_radius - info.max_radius,
                        info.planet_radius - info.min_radius)
                raise tornado.web.HTTPError(400, log_message=msg,
                                            reason=msg)
        else:
            # The source depth must coincide with the one in the database.
            if source.depth_in_m != info.source_depth * 1000:
                    msg = "Source depth must be: %.1f km" % info.source_depth
                    raise tornado.web.HTTPError(400, log_message=msg,
                                                reason=msg)