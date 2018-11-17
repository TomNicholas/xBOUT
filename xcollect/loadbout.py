
from warnings import warn
from pathlib import Path
from itertools import zip_longest

from numpy import asscalar
import xarray


def _auto_open_mfboutdataset(datapath, chunks, info):
    path = Path(datapath)

    filepaths, filetype = _expand_filepaths(path)

    # Open just one file to read processor splitting
    nxpe, nype, mxg, myg = _read_splitting(filepaths[0])

    # TODO Special case needed for case of just one dump file?

    paths_grid, concat_dims = _arrange_for_concatenation(filepaths, nxpe, nype)

    ds = xarray.open_mfdataset(paths_grid, concat_dims=concat_dims,
                               engine=filetype, chunks=chunks,
                               infer_order_from_coords=False)

    ds, metadata = _strip_metadata(ds)

    trimmed_ds = _trim(ds, ghosts={'x': mxg, 'y': myg},
                    proc_splitting={'x': nxpe, 'y': nype},
                    guards={'x': mxg, 'y': myg}, keep_guards=True)

    return trimmed_ds, metadata


def _expand_filepaths(path):
    """Determines filetypes and opens all dump files."""

    filetype = _check_filetype(path)

    filepaths = _expand_wildcards(path)

    if len(filepaths) > 128:
        warn("Trying to open a large number of files - setting xarray's"
             " `file_cache_maxsize` global option to {} to accommodate this. "
             "Recommend using `xr.set_options(file_cache_maxsize=NUM)`"
             " to explicitly set this to a large enough value."
             .format(str(len(filepaths))), UserWarning)
        xarray.set_options(file_cache_maxsize=len(filepaths))

    return filepaths, filetype


def _check_filetype(path):
    if path.suffix == '.nc':
        filetype = 'netcdf4'
    elif path.suffix == '.h5netcdf':
        filetype = 'h5netcdf'
    else:
        raise IOError(
            'Do not know how to read the supplied file extension: ' + path.suffix)

    return filetype


def _expand_wildcards(path):
    """Return list of filepaths matching wildcard"""

    # Find first parent directory which does not contain a wildcard
    base_dir = next(parent for parent in path.parents if '*' not in str(parent))

    # Find path relative to parent
    search_pattern = str(path.relative_to(base_dir))

    # Search this relative path from the parent directory for all files matching user input
    filepaths = list(base_dir.glob(search_pattern))

    # Sort by numbers in filepath before returning
    return sorted(filepaths, key=lambda filepath: str(filepath))


def _read_splitting(filepath):
    # TODO make sure dask is being used here?
    ds = xarray.open_dataset(str(filepath))

    # TODO check that BOUT doesn't ever set the number of guards to be different to the number of ghosts

    nxpe, nype = ds['NXPE'].values, ds['NYPE'].values
    mxg, myg = ds['MXG'].values, ds['MYG'].values

    # Avoid opening this file twice
    ds.close()

    return nxpe, nype, mxg, myg


def _old_arrange_for_concatenation(filepaths, nxpe=1, nype=1):
    """
    Arrange filepaths into a nested list-of-lists which represents their
    ordering across different processors and consecutive simulation runs.

    Filepaths must be a sorted list.
    """

    nprocs = nxpe * nype

    runs = _grouper(filepaths, nprocs)

    path_grid = []
    for run in runs:
        run_paths = []

        xrows = _grouper(run, nxpe)

        run_paths.append([xrows])

        path_grid.append([run_paths])

    concat_dims = []
    if nxpe > 1:
        concat_dims.append('x')
    if nype > 1:
        concat_dims.append('y')
    if len(filepaths) > nprocs:
        concat_dims.append('t')

    return path_grid, concat_dims


def _arrange_for_concatenation(filepaths, nxpe=1, nype=1):
    """
    Arrange filepaths into a nested list-of-lists which represents their
    ordering across different processors and consecutive simulation runs.

    Filepaths must be a sorted list.
    """

    nprocs = nxpe * nype

    path_grid = [[[yrow for yrow in chunks(xcol, nype)]
                        for xcol in chunks(run, nxpe)]
                        for run in chunks(filepaths, nprocs)]

    print(path_grid)

#    path_grid = list(chunks(filepaths, nprocs))

    concat_dims = []
    if len(filepaths) > nprocs:
        concat_dims.append('t')
    if nxpe > 1:
        concat_dims.append('x')
    if nype > 1:
        concat_dims.append('y')

    return path_grid, concat_dims


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def _grouper(iterable, n, fillvalue=None):
    """
    Collect data from an iterable into fixed-length chunks or blocks.
    Adapted from an itertools recipe.
    """
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    print(args)
    return zip_longest(*args, fillvalue=fillvalue)


def _trim(ds, ghosts=None, proc_splitting=None, guards=None, keep_guards=True):
    """
    Trims all ghost and guard cells off the combined dataset produced by
    `open_mfdataset()`.

    Parameters
    ----------
    ghosts : dict, optional

    proc_splitting : dict, optional

    guards : dict, optional

    keep_guards : dict, optional

    """

    for dim in ds.dims:
        # Optionally remove any guard cells
        if not keep_guards.get(dim, default=True) or not keep_guards:
            if isinstance(guards[dim], tuple):
                lower_guards, upper_guards = guards[dim]
            elif isinstance(guards[dim], int):
                lower_guards, upper_guards = guards[dim], guards[dim]
            elif not guards[dim]:
                lower_guards, upper_guards = ghosts[dim], ghosts[dim]
            else:
                raise ValueError("guards[{}] is neither an integer nor a tuple"
                                 " of integers".format(dim))
        else:
            ...

        #proc_length =

        # Remove any ghost cells
    selection = None
    trimmed_ds = ds.isel(**selection)
    return trimmed_ds


def _strip_metadata(ds):
    """
    Extract the metadata (nxpe, myg etc.) from the Dataset.

    Assumes that all scalar variables are metadata, not physical data!
    """

    # Find only the scalar variables
    variables = list(ds.variables)
    scalar_vars = [var for var in variables if not any(dim in ['t', 'x', 'y', 'z'] for dim in ds[var].dims)]

    # Save metadata as a dictionary
    metadata_vals = [asscalar(ds[var].values) for var in scalar_vars]
    metadata = dict(zip(scalar_vars, metadata_vals))

    return ds.drop(scalar_vars), metadata