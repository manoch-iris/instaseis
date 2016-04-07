#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:copyright:
    Lion Krischer (krischer@geophysik.uni-muenchen.de), 2016
:license:
    GNU Lesser General Public License, Version 3 [non-commercial/academic use]
    (http://www.gnu.org/copyleft/lgpl.html)
"""
from __future__ import absolute_import, division, print_function

import collections
import os

from .. import InstaseisError, InstaseisNotFoundError
from .instaseis_db import InstaseisDB


def find_and_open_files(path, *args, **kwargs):
    """
    Find and open Instaseis databases with the corresponding database
    interface.

    Will recursively search the path and return an instaseis database class
    if possible.
    """
    found_files = []
    for root, dirs, filenames in os.walk(path, followlinks=True):
        # Limit depth of filetree traversal
        nested_levels = os.path.relpath(root, path).split(
            os.path.sep)
        if len(nested_levels) >= 4:
            del dirs[:]
        if "ordered_output.nc4" not in filenames:
            continue
        found_files.append(os.path.join(root, "ordered_output.nc4"))

    if len(found_files) == 0:
        raise InstaseisNotFoundError(
            "No suitable netCDF files found under '%s'" % path)
    elif len(found_files) not in [1, 2, 4]:
        raise InstaseisError(
            "1, 2 or 4 netCDF must be present in the folder structure. "
            "Found %i: \t%s" % (len(found_files),
                                "\n\t".join(found_files)))

    # Parse to find the correct components.
    netcdf_files = collections.defaultdict(list)
    patterns = ["PX", "PZ", "MZZ", "MXX_P_MYY", "MXZ_MYZ", "MXY_MXX_M_MYY"]
    for filename in found_files:
        s = os.path.relpath(filename, path).split(os.path.sep)
        for p in patterns:
            if p in s:
                netcdf_files[p].append(filename)

    # Assert at most one file per type.
    for key, files in netcdf_files.items():
        if len(files) != 1:
            raise InstaseisError(
                "Found %i files for component %s:\n\t%s" % (
                    len(files), key, "\n\t".join(files)))
        netcdf_files[key] = files[0]

    # Two valid cases.
    if "PX" in netcdf_files or "PZ" in netcdf_files:
        return InstaseisDB(db_path=path, netcdf_files=netcdf_files,
                           type="reciprocal", *args, **kwargs)
    elif "MZZ" in netcdf_files or "MXX_P_MYY" in netcdf_files or \
            "MXZ_MYZ" in netcdf_files or "MXY_MXX_M_MYY" in netcdf_files:
        if sorted(netcdf_files.keys()) != sorted([
                "MZZ", "MXX_P_MYY", "MXZ_MYZ", "MXY_MXX_M_MYY"]):
            raise InstaseisError(
                "Expecting all four elemental moment tensor subfolders "
                "to be present.")
        return InstaseisDB(db_path=path, netcdf_files=netcdf_files,
                           type="forward", *args, **kwargs)
    else:
        raise InstaseisError(
            "Could not find any suitable netCDF files. Did you pass the "
            "correct directory? E.g. if the 'ordered_output.nc4' files "
            "are located in '/path/to/PZ/Data', please pass '/path/to/' "
            "to Instaseis.")