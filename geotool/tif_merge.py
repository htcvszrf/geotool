
import math
import os.path
import sys
import time
from osgeo import gdal


progress = gdal.TermProgress_nocb

__version__ = '$id$'[5:-1]
verbose = 0
quiet = 0


def DoesDriverHandleExtension(drv, ext):
    exts = drv.GetMetadataItem(gdal.DMD_EXTENSIONS)
    return exts is not None and exts.lower().find(ext.lower()) >= 0


def GetExtension(filename):
    ext = os.path.splitext(filename)[1]
    if ext.startswith('.'):
        ext = ext[1:]
    return ext


def GetOutputDriversFor(filename):
    drv_list = []
    ext = GetExtension(filename)
    for i in range(gdal.GetDriverCount()):
        drv = gdal.GetDriver(i)
        if (drv.GetMetadataItem(gdal.DCAP_CREATE) is not None or
            drv.GetMetadataItem(gdal.DCAP_CREATECOPY) is not None) and \
           drv.GetMetadataItem(gdal.DCAP_RASTER) is not None:
            if len(ext) > 0 and DoesDriverHandleExtension(drv, ext):
                drv_list.append(drv.ShortName)
            else:
                prefix = drv.GetMetadataItem(gdal.DMD_CONNECTION_PREFIX)
                if prefix is not None and filename.lower().startswith(prefix.lower()):
                    drv_list.append(drv.ShortName)

    # GMT is registered before netCDF for opening reasons, but we want
    # netCDF to be used by default for output.
    if ext.lower() == 'nc' and len(drv_list) == 0 and \
       drv_list[0].upper() == 'GMT' and drv_list[1].upper() == 'NETCDF':
        drv_list = ['NETCDF', 'GMT']

    return drv_list


def GetOutputDriverFor(filename):
    drv_list = GetOutputDriversFor(filename)
    ext = None
    if len(drv_list) == 0:
        ext = GetExtension(filename)
        if len(ext) == 0:
            return 'GTiff'
        else:
            raise Exception("Cannot guess driver for %s" % filename)
    elif len(drv_list) > 1:
        print("Several drivers matching %s extension. Using %s" % (ext, drv_list[0]))
    return drv_list[0]


# =============================================================================
def raster_copy(s_fh, s_xoff, s_yoff, s_xsize, s_ysize, s_band_n,
                t_fh, t_xoff, t_yoff, t_xsize, t_ysize, t_band_n,
                nodata=None):

    if verbose != 0:
        print('Copy %d,%d,%d,%d to %d,%d,%d,%d.'
              % (s_xoff, s_yoff, s_xsize, s_ysize,
                 t_xoff, t_yoff, t_xsize, t_ysize))

    if nodata is not None:
        return raster_copy_with_nodata(
            s_fh, s_xoff, s_yoff, s_xsize, s_ysize, s_band_n,
            t_fh, t_xoff, t_yoff, t_xsize, t_ysize, t_band_n,
            nodata)

    s_band = s_fh.GetRasterBand(s_band_n)
    m_band = None
    # Works only in binary mode and doesn't take into account
    # intermediate transparency values for compositing.
    if s_band.GetMaskFlags() != gdal.GMF_ALL_VALID:
        m_band = s_band.GetMaskBand()
    elif s_band.GetColorInterpretation() == gdal.GCI_AlphaBand:
        m_band = s_band
    if m_band is not None:
        return raster_copy_with_mask(
            s_fh, s_xoff, s_yoff, s_xsize, s_ysize, s_band_n,
            t_fh, t_xoff, t_yoff, t_xsize, t_ysize, t_band_n,
            m_band)

    s_band = s_fh.GetRasterBand(s_band_n)
    t_band = t_fh.GetRasterBand(t_band_n)

    data = s_band.ReadRaster(s_xoff, s_yoff, s_xsize, s_ysize,
                             t_xsize, t_ysize, t_band.DataType)
    t_band.WriteRaster(t_xoff, t_yoff, t_xsize, t_ysize,
                       data, t_xsize, t_ysize, t_band.DataType)

    return 0

# =============================================================================


def raster_copy_with_nodata(s_fh, s_xoff, s_yoff, s_xsize, s_ysize, s_band_n,
                            t_fh, t_xoff, t_yoff, t_xsize, t_ysize, t_band_n,
                            nodata):
    try:
        import numpy as Numeric
    except ImportError:
        import Numeric

    s_band = s_fh.GetRasterBand(s_band_n)
    t_band = t_fh.GetRasterBand(t_band_n)

    data_src = s_band.ReadAsArray(s_xoff, s_yoff, s_xsize, s_ysize,
                                  t_xsize, t_ysize)
    data_dst = t_band.ReadAsArray(t_xoff, t_yoff, t_xsize, t_ysize)

    if not Numeric.isnan(nodata):
        nodata_test = Numeric.equal(data_src, nodata)
    else:
        nodata_test = Numeric.isnan(data_src)

    to_write = Numeric.choose(nodata_test, (data_src, data_dst))

    t_band.WriteArray(to_write, t_xoff, t_yoff)

    return 0

# =============================================================================


def raster_copy_with_mask(s_fh, s_xoff, s_yoff, s_xsize, s_ysize, s_band_n,
                          t_fh, t_xoff, t_yoff, t_xsize, t_ysize, t_band_n,
                          m_band):
    try:
        import numpy as Numeric
    except ImportError:
        import Numeric

    s_band = s_fh.GetRasterBand(s_band_n)
    t_band = t_fh.GetRasterBand(t_band_n)

    data_src = s_band.ReadAsArray(s_xoff, s_yoff, s_xsize, s_ysize,
                                  t_xsize, t_ysize)
    data_mask = m_band.ReadAsArray(s_xoff, s_yoff, s_xsize, s_ysize,
                                   t_xsize, t_ysize)
    data_dst = t_band.ReadAsArray(t_xoff, t_yoff, t_xsize, t_ysize)

    mask_test = Numeric.equal(data_mask, 0)
    to_write = Numeric.choose(mask_test, (data_src, data_dst))

    t_band.WriteArray(to_write, t_xoff, t_yoff)

    return 0

# =============================================================================


def names_to_fileinfos(names):
    """
    Translate a list of GDAL filenames, into file_info objects.

    names -- list of valid GDAL dataset names.

    Returns a list of file_info objects.  There may be less file_info objects
    than names if some of the names could not be opened as GDAL files.
    """

    file_infos = []
    for name in names:
        fi = file_info()
        if fi.init_from_name(name) == 1:
            file_infos.append(fi)

    return file_infos

# *****************************************************************************


class file_info:
    """A class holding information about a GDAL file."""

    def init_from_name(self, filename):
        """
        Initialize file_info from filename

        filename -- Name of file to read.

        Returns 1 on success or 0 if the file can't be opened.
        """
        fh = gdal.Open(filename)
        if fh is None:
            return 0

        self.filename = filename
        self.bands = fh.RasterCount
        self.xsize = fh.RasterXSize
        self.ysize = fh.RasterYSize
        self.band_type = fh.GetRasterBand(1).DataType
        self.projection = fh.GetProjection()
        self.geotransform = fh.GetGeoTransform()
        self.ulx = self.geotransform[0]
        self.uly = self.geotransform[3]
        self.lrx = self.ulx + self.geotransform[1] * self.xsize
        self.lry = self.uly + self.geotransform[5] * self.ysize

        ct = fh.GetRasterBand(1).GetRasterColorTable()
        if ct is not None:
            self.ct = ct.Clone()
        else:
            self.ct = None

        return 1

    def report(self):
        print('Filename: ' + self.filename)
        print('File Size: %dx%dx%d'
              % (self.xsize, self.ysize, self.bands))
        print('Pixel Size: %f x %f'
              % (self.geotransform[1], self.geotransform[5]))
        print('UL:(%f,%f)   LR:(%f,%f)'
              % (self.ulx, self.uly, self.lrx, self.lry))

    def copy_into(self, t_fh, s_band=1, t_band=1, nodata_arg=None):
        """
        Copy this files image into target file.

        This method will compute the overlap area of the file_info objects
        file, and the target gdal.Dataset object, and copy the image data
        for the common window area.  It is assumed that the files are in
        a compatible projection ... no checking or warping is done.  However,
        if the destination file is a different resolution, or different
        image pixel type, the appropriate resampling and conversions will
        be done (using normal GDAL promotion/demotion rules).

        t_fh -- gdal.Dataset object for the file into which some or all
        of this file may be copied.

        Returns 1 on success (or if nothing needs to be copied), and zero one
        failure.
        """
        t_geotransform = t_fh.GetGeoTransform()
        t_ulx = t_geotransform[0]
        t_uly = t_geotransform[3]
        t_lrx = t_geotransform[0] + t_fh.RasterXSize * t_geotransform[1]
        t_lry = t_geotransform[3] + t_fh.RasterYSize * t_geotransform[5]

        # figure out intersection region
        tgw_ulx = max(t_ulx, self.ulx)
        tgw_lrx = min(t_lrx, self.lrx)
        if t_geotransform[5] < 0:
            tgw_uly = min(t_uly, self.uly)
            tgw_lry = max(t_lry, self.lry)
        else:
            tgw_uly = max(t_uly, self.uly)
            tgw_lry = min(t_lry, self.lry)

        # do they even intersect?
        if tgw_ulx >= tgw_lrx:
            return 1
        if t_geotransform[5] < 0 and tgw_uly <= tgw_lry:
            return 1
        if t_geotransform[5] > 0 and tgw_uly >= tgw_lry:
            return 1

        # compute target window in pixel coordinates.
        tw_xoff = int((tgw_ulx - t_geotransform[0]) / t_geotransform[1] + 0.1)
        tw_yoff = int((tgw_uly - t_geotransform[3]) / t_geotransform[5] + 0.1)
        tw_xsize = int((tgw_lrx - t_geotransform[0]) / t_geotransform[1] + 0.5) \
            - tw_xoff
        tw_ysize = int((tgw_lry - t_geotransform[3]) / t_geotransform[5] + 0.5) \
            - tw_yoff

        if tw_xsize < 1 or tw_ysize < 1:
            return 1

        # Compute source window in pixel coordinates.
        sw_xoff = int((tgw_ulx - self.geotransform[0]) / self.geotransform[1])
        sw_yoff = int((tgw_uly - self.geotransform[3]) / self.geotransform[5])
        sw_xsize = int((tgw_lrx - self.geotransform[0]) /
                       self.geotransform[1] + 0.5) - sw_xoff
        sw_ysize = int((tgw_lry - self.geotransform[3]) /
                       self.geotransform[5] + 0.5) - sw_yoff

        if sw_xsize < 1 or sw_ysize < 1:
            return 1

        # Open the source file, and copy the selected region.
        s_fh = gdal.Open(self.filename)

        return raster_copy(s_fh, sw_xoff, sw_yoff, sw_xsize, sw_ysize, s_band,
                           t_fh, tw_xoff, tw_yoff, tw_xsize, tw_ysize, t_band,
                           nodata_arg)

import glob

def run_merge(tif_dir, out_path):

    tif_list = glob.glob(os.path.join(tif_dir, "*.tif"))
    # argv = None
    global verbose, quiet
    verbose = 0
    quiet = 0

    names = tif_list
    format = None
    out_file = out_path

    ulx = None
    psize_x = None
    separate = 0
    copy_pct = 0
    nodata = None
    a_nodata = None
    create_options = []
    pre_init = []
    band_type = None
    createonly = 0
    bTargetAlignedPixels = False
    start_time = time.time()

    gdal.AllRegister()

    if format is None:
        format = GetOutputDriverFor(out_file)

    Driver = gdal.GetDriverByName(format)
    if Driver is None:
        print('Format driver %s not found, pick a supported driver.' % format)
        sys.exit(1)

    DriverMD = Driver.GetMetadata()
    if 'DCAP_CREATE' not in DriverMD:
        print('Format driver %s does not support creation and piecewise writing.\nPlease select a format that does, such as GTiff (the default) or HFA (Erdas Imagine).' % format)
        sys.exit(1)

    # Collect information on all the source files.
    file_infos = names_to_fileinfos(names)


    ulx = file_infos[0].ulx
    uly = file_infos[0].uly
    lrx = file_infos[0].lrx
    lry = file_infos[0].lry

    for fi in file_infos:
        ulx = min(ulx, fi.ulx)
        uly = max(uly, fi.uly)
        lrx = max(lrx, fi.lrx)
        lry = min(lry, fi.lry)


    psize_x = file_infos[0].geotransform[1]
    psize_y = file_infos[0].geotransform[5]

    if band_type is None:
        band_type = file_infos[0].band_type

    # Try opening as an existing file.
    gdal.PushErrorHandler('CPLQuietErrorHandler')
    try:
        t_fh = gdal.Open(out_file, gdal.GA_Update)
    except Exception:
        t_fh = None

    # Create output file if it does not already exist.
    if t_fh is None:

        if bTargetAlignedPixels:
            ulx = math.floor(ulx / psize_x) * psize_x
            lrx = math.ceil(lrx / psize_x) * psize_x
            lry = math.floor(lry / -psize_y) * -psize_y
            uly = math.ceil(uly / -psize_y) * -psize_y

        geotransform = [ulx, psize_x, 0, uly, 0, psize_y]

        xsize = int((lrx - ulx) / geotransform[1] + 0.5)
        ysize = int((lry - uly) / geotransform[5] + 0.5)

        if separate != 0:
            bands = 0
            for fi in file_infos:
                bands = bands + fi.bands
        else:
            bands = file_infos[0].bands

        t_fh = Driver.Create(out_file, xsize, ysize, bands,
                             band_type, create_options)
        if t_fh is None:
            print('Creation failed, terminating gdal_merge.')
            sys.exit(1)

        t_fh.SetGeoTransform(geotransform)
        t_fh.SetProjection(file_infos[0].projection)

        if copy_pct:
            t_fh.GetRasterBand(1).SetRasterColorTable(file_infos[0].ct)


    # Do we need to set nodata value ?
    if a_nodata is not None:
        for i in range(t_fh.RasterCount):
            t_fh.GetRasterBand(i + 1).SetNoDataValue(a_nodata)

    # Do we need to pre-initialize the whole mosaic file to some value?
    if pre_init is not None:
        if t_fh.RasterCount <= len(pre_init):
            for i in range(t_fh.RasterCount):
                t_fh.GetRasterBand(i + 1).Fill(pre_init[i])
        elif len(pre_init) == 1:
            for i in range(t_fh.RasterCount):
                t_fh.GetRasterBand(i + 1).Fill(pre_init[0])

    # Copy data from source files into output file.
    t_band = 1

    if quiet == 0 and verbose == 0:
        progress(0.0)
    fi_processed = 0

    for fi in file_infos:
        if createonly != 0:
            continue

        if verbose != 0:
            print("")
            print("Processing file %5d of %5d, %6.3f%% completed in %d minutes."
                  % (fi_processed + 1, len(file_infos),
                     fi_processed * 100.0 / len(file_infos),
                     int(round((time.time() - start_time) / 60.0))))
            fi.report()

        if separate == 0:
            for band in range(1, bands + 1):
                fi.copy_into(t_fh, band, band, nodata)
        else:
            for band in range(1, fi.bands + 1):
                fi.copy_into(t_fh, band, t_band, nodata)
                t_band = t_band + 1
        fi_processed += 1
        if quiet == 0 and verbose == 0:
            progress(fi_processed / float(len(file_infos)))
