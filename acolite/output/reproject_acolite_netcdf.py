## def reproject_acolite_netcdf
## reprojects ACOLITE NetCDF to a defined projection and extent
## written by Quinten Vanhellemont, RBINS
## 2022-01-04
## modifications: 2022-01-05 (QV) acolite function, changed handling provided x and y ranges

def reproject_acolite_netcdf(ncf, output = None, settings = {}, target_file=None):

    import os
    from pyproj import Proj

    import acolite as ac
    import numpy as np
    from pyresample.bilinear import NumpyBilinearResampler
    from pyresample import geometry

    ## read gatts
    gatts = ac.shared.nc_gatts(ncf)
    if ('sensor' not in gatts):
        print('No sensor attribute in file {}'.format(ncf))
        return()

    ## read datasets
    datasets = ac.shared.nc_datasets(ncf)
    if ('lat' not in datasets) or ('lon' not in datasets):
        print('No lat/lon found in file {}'.format(ncf))
        return()

    ## parse settings
    setu = ac.acolite.settings.parse(gatts['sensor'], settings=settings)

    ## projection
    if setu['output_projection_epsg'] is not None:
        #projection = '+init=EPSG:{}'.format(setu['output_projection_epsg'])
        if 'EPSG' not in setu['output_projection_epsg']:
            projection = 'EPSG:{}'.format(setu['output_projection_epsg'])
        else:
            projection = '{}'.format(setu['output_projection_epsg'])
    elif setu['output_projection_proj4'] is not None:
        projection = setu['output_projection_proj4']
    else:
        print('No EPSG or proj4 string provided.')
        return()

    if setu['output_projection_limit'] is not None:
        if len(setu['output_projection_limit']) != 4:
            print('Provide a four element output_projection_limit.')
            return()
        else:
            limit = [float(v) for v in setu['output_projection_limit']]
    else:
        if not setu['output_projection_metres']:
            print('Provide a four element output_projection_limit.')
            return()

    if setu['output_projection_resolution'] is not None:
        if len(setu['output_projection_resolution']) != 2:
            print('Provide a two element target_pixel_size.')
            return()
        else:
            target_pixel_size = [float(v) for v in setu['output_projection_resolution']]

    ## user provided x and yrange
    if setu['output_projection_metres']:
        xrange_region = setu['output_projection_xrange']
        yrange_region = setu['output_projection_yrange']
        if (xrange_region is None) or  (yrange_region is None):
            print('Provide a output_projection_xrange and output_projection_yrange.')
            return()
        if len(xrange_region) != 2:
            print('Provide a two element output_projection_xrange.')
            return()
        if len(yrange_region) != 2:
            print('Provide a two element output_projection_yrange.')
            return()

    ## create output file name
    bn = os.path.basename(ncf)
    bd = os.path.dirname(ncf)
    oname, nc = os.path.splitext(bn)
    if output is not None:
        bd = '{}'.format(output)
    elif setu['output'] is not None:
        bd = '{}'.format(setu['output'])
    ## add requested name or "reprojected"
    oname = '{}_{}'.format(oname, setu['output_projection_name'] if setu['output_projection_name'] is not None else "reprojected")
    ncfo = '{}/{}{}'.format(bd, oname, nc)

    print('Setting up target projection.')
    p = Proj(projection)

    ## find region extent
    if not setu['output_projection_metres']:
        ## project lat lon to metres
        xrange_raw, yrange_raw = p((limit[1],limit[1],limit[3],limit[3]),
                                   (limit[0],limit[2],limit[2],limit[0]))
        xrange_raw = (min(xrange_raw), max(xrange_raw))
        yrange_raw = (min(yrange_raw), max(yrange_raw))
        xrange_region = [xrange_raw[0] - (xrange_raw[0] % target_pixel_size[0]*2), xrange_raw[1]+target_pixel_size[0]*2-(xrange_raw[1] % target_pixel_size[0]*2)]
        yrange_region = [yrange_raw[1]+target_pixel_size[1]*2-(yrange_raw[1] % target_pixel_size[1]*2), yrange_raw[0] - (yrange_raw[0] % target_pixel_size[1]*2)]

    ## align grid to pixel size
    if setu['output_projection_resolution_align']:
        x_grid_off = xrange_region[0]%target_pixel_size[0], xrange_region[1]%target_pixel_size[0]
        y_grid_off = yrange_region[0]%target_pixel_size[1], yrange_region[1]%target_pixel_size[1]
        xrange = (xrange_region[0]-x_grid_off[0]), (xrange_region[1]+(target_pixel_size[0]-x_grid_off[1]))
        yrange = (yrange_region[0]-y_grid_off[0]), (yrange_region[1]+(target_pixel_size[0]-y_grid_off[1]))
    else:
        xrange = [xrange_region[0], xrange_region[1]]
        yrange = [yrange_region[0], yrange_region[1]]

    ## pixel sizes
    ny = int((yrange[0] - yrange[1])/target_pixel_size[1])
    nx = int((xrange[1] - xrange[0])/target_pixel_size[0])
    print(xrange, yrange)
    print(nx, ny)

    ## set up projection dict and nc_projection
    dct = {'xrange': xrange, 'yrange': yrange, 'p': p,
           'pixel_size': target_pixel_size, 'xdim': nx, 'ydim': ny}
    nc_projection = ac.shared.projection_netcdf(dct, add_half_pixel=True)


    ## set up target definition
    target_definition = geometry.AreaDefinition('area_id', 'description', 'proj_id',
                                          projection, nx, ny, [xrange[0],yrange[1],xrange[1],yrange[0]])

    ## read lat/lon
    lat = ac.shared.nc_data(ncf, 'lat')
    lon = ac.shared.nc_data(ncf, 'lon')

    ## set up source definition
    source_definition = geometry.SwathDefinition(lons=lon, lats=lat)

    ## set up resampler
    if setu['output_projection_resampling_method'] == 'bilinear':
        resampler = NumpyBilinearResampler(source_definition, target_definition, 30e3)

    ## run through datasets
    new = True
    for ds in datasets:
        print('Reprojecting {} to {} {}x{}'.format(ds, projection, nx, ny))
        data_in, att = ac.shared.nc_data(ncf, ds, attributes=True)
        data_out = resampler.resample(data_in)
        data_in = None

        lsd = None
        if ds not in ['lat', 'lon', 'vza', 'sza', 'vaa', 'saa', 'raa']:
            lsd = setu['netcdf_compression_least_significant_digit']

        ac.output.nc_write(ncfo, ds, data_out, attributes = att,
                           netcdf_compression=setu['netcdf_compression'],
                           netcdf_compression_level=setu['netcdf_compression_level'],
                           netcdf_compression_least_significant_digit=lsd,
                           nc_projection = nc_projection,
                           dataset_attributes = att, new = new)
        new = False
    print('Wrote {}'.format(ncfo))
    return(ncfo)
