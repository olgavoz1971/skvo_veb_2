"""Tests for the shared cutout cache and ReRetrieve on the TESS cutout page."""

import os
from pathlib import Path
from unittest import mock

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from skvo_veb.utils import lightkurve_cache, tess_cache, tess_processor
from skvo_veb.utils.my_tools import PipeException

COORD = SkyCoord(ra=35.471341 * u.deg, dec=-17.67794 * u.deg)
NAME = 'tess-s0030-2-3_35.471341_-17.677940_11x11_astrocut.fits'


def _touch(directory, name, content=b'x'):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(content)
    return path


def _search_row(sector=30):
    """A one-row stand-in for a TESScut search result whose download writes a cutout file."""
    row = mock.MagicMock()
    row.table = {'sequence_number': [sector], 'targetid': ['TIC 1']}
    search = mock.MagicMock()
    search.__getitem__.return_value = row
    return search, row


def _fake_download(content):
    """Returns a ``download`` replacement that writes one cutout into ``<download_dir>/tesscut``."""
    def download(download_dir, cutout_size):
        _touch(Path(download_dir) / 'tesscut', NAME, content)
    return download


@pytest.fixture
def cache_root(tmp_path):
    with mock.patch.object(lightkurve_cache, 'get_lightkurve_cache_dir', return_value=str(tmp_path)):
        yield tmp_path


def test_find_cached_tesscut_matches_only_sector_size_and_position(tmp_path):
    cut = tmp_path / 'tesscut'
    target = _touch(cut, 'tess-s0030-2-3_35.471341_-17.677940_11x11_astrocut.fits')
    near = _touch(cut, 'tess-s0030-2-3_35.471363_-17.677935_11x11_astrocut.fits')
    _touch(cut, 'tess-s0030-2-3_35.471363_-17.677935_15x15_astrocut.fits')
    _touch(cut, 'tess-s0097-2-3_35.471341_-17.677940_11x11_astrocut.fits')
    _touch(cut, 'tess-s0030-2-3_85.216525_-31.351107_11x11_astrocut.fits')

    found = lightkurve_cache.find_cached_tesscut_files(str(tmp_path), 30, 11, COORD)

    assert found == [str(target), str(near)]


def test_find_cached_tesscut_without_folder_finds_nothing(tmp_path):
    assert lightkurve_cache.find_cached_tesscut_files(str(tmp_path), 30, 11, COORD) == []


def test_fetch_cutout_cache_hit_does_not_download(cache_root):
    cached = _touch(cache_root / 'tesscut', NAME)
    search, row = _search_row()
    with mock.patch.object(lightkurve_cache, '_read_tesscut_file', return_value='TPF') as read:
        result = lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD)
    assert result == 'TPF'
    read.assert_called_once_with(str(cached), row)
    row.download.assert_not_called()


def test_fetch_cutout_miss_downloads_into_temp_folder_then_moves_into_cache(cache_root):
    search, row = _search_row()
    row.download.side_effect = _fake_download(b'new')
    with mock.patch.object(lightkurve_cache, '_read_tesscut_file', return_value='TPF'):
        lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD)
    assert (cache_root / 'tesscut' / NAME).read_bytes() == b'new'
    assert not [p for p in os.listdir(cache_root) if p.startswith('.tmp_tesscut_')]
    assert row.download.call_args.kwargs['download_dir'] != str(cache_root)


def test_fetch_cutout_refresh_replaces_cached_file(cache_root):
    _touch(cache_root / 'tesscut', NAME, b'old')
    search, row = _search_row()
    row.download.side_effect = _fake_download(b'fresh')
    with mock.patch.object(lightkurve_cache, '_read_tesscut_file', return_value='TPF'):
        lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD, force_fresh=True)
    assert (cache_root / 'tesscut' / NAME).read_bytes() == b'fresh'
    row.download.assert_called_once()


def test_fetch_cutout_unreadable_cached_file_is_removed_and_downloaded_again(cache_root):
    _touch(cache_root / 'tesscut', NAME, b'broken')
    search, row = _search_row()
    row.download.side_effect = _fake_download(b'good')
    with mock.patch.object(lightkurve_cache, '_read_tesscut_file', side_effect=[OSError('truncated'), 'TPF']):
        assert lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD) == 'TPF'
    assert (cache_root / 'tesscut' / NAME).read_bytes() == b'good'


def test_fetch_cutout_download_error_is_reported_and_leaves_cache_untouched(cache_root):
    _touch(cache_root / 'tesscut', NAME, b'old')
    search, row = _search_row()
    row.download.side_effect = RuntimeError('504')
    with pytest.raises(PipeException, match='504'):
        lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD, force_fresh=True)
    assert (cache_root / 'tesscut' / NAME).read_bytes() == b'old'
    assert not [p for p in os.listdir(cache_root) if p.startswith('.tmp_tesscut_')]


def test_fetch_cutout_requires_exactly_one_downloaded_file(cache_root):
    search, row = _search_row()
    row.download.side_effect = lambda download_dir, cutout_size: None
    with pytest.raises(PipeException, match='expected exactly one'):
        lightkurve_cache.fetch_tesscut_pixel_file(search, 0, 11, COORD)


TPF_REL = os.path.join('mastDownload', 'TESS', 'obs1', 'tpf.fits')


def _tpf_search(cache_root):
    """A one-row SPOC search stand-in whose cache path is ``<cache_root>/mastDownload/TESS/obs1/tpf.fits``."""
    search, row = _search_row()
    return search, row, mock.patch.object(lightkurve_cache, 'spoc_tpf_cache_path',
                                          return_value=str(cache_root / TPF_REL))


def _fake_tpf_download(content):
    """Returns a ``download`` replacement that writes the TPF below the given download folder."""
    def download(download_dir):
        _touch((Path(download_dir) / TPF_REL).parent, 'tpf.fits', content)
    return download


def test_fetch_tpf_cache_hit_does_not_download(cache_root):
    _touch((cache_root / TPF_REL).parent, 'tpf.fits')
    search, row, path_patch = _tpf_search(cache_root)
    with path_patch, mock.patch.object(lightkurve_cache.lk, 'read', return_value='TPF'):
        assert lightkurve_cache.fetch_spoc_tpf(search, 0) == 'TPF'
    row.download.assert_not_called()


def test_fetch_tpf_miss_downloads_into_temp_folder_then_publishes(cache_root):
    search, row, path_patch = _tpf_search(cache_root)
    row.download.side_effect = _fake_tpf_download(b'new')
    with path_patch, mock.patch.object(lightkurve_cache.lk, 'read', return_value='TPF'):
        lightkurve_cache.fetch_spoc_tpf(search, 0)
    assert (cache_root / TPF_REL).read_bytes() == b'new'
    assert row.download.call_args.kwargs['download_dir'] != str(cache_root)
    assert not [p for p in os.listdir(cache_root) if p.startswith('.tmp_tpf_')]


def test_fetch_tpf_refresh_replaces_cached_file(cache_root):
    _touch((cache_root / TPF_REL).parent, 'tpf.fits', b'old')
    search, row, path_patch = _tpf_search(cache_root)
    row.download.side_effect = _fake_tpf_download(b'fresh')
    with path_patch, mock.patch.object(lightkurve_cache.lk, 'read', return_value='TPF'):
        lightkurve_cache.fetch_spoc_tpf(search, 0, force_fresh=True)
    assert (cache_root / TPF_REL).read_bytes() == b'fresh'


def test_fetch_tpf_unreadable_cached_file_is_removed_and_downloaded_again(cache_root):
    _touch((cache_root / TPF_REL).parent, 'tpf.fits', b'broken')
    search, row, path_patch = _tpf_search(cache_root)
    row.download.side_effect = _fake_tpf_download(b'good')
    with path_patch, mock.patch.object(lightkurve_cache.lk, 'read',
                                       side_effect=[OSError('truncated'), 'ok', 'TPF']):
        assert lightkurve_cache.fetch_spoc_tpf(search, 0) == 'TPF'
    assert (cache_root / TPF_REL).read_bytes() == b'good'


def test_fetch_tpf_incomplete_download_is_never_published(cache_root):
    _touch((cache_root / TPF_REL).parent, 'tpf.fits', b'old')
    search, row, path_patch = _tpf_search(cache_root)
    row.download.side_effect = _fake_tpf_download(b'half')
    with path_patch, mock.patch.object(lightkurve_cache.lk, 'read', side_effect=OSError('too small')):
        with pytest.raises(PipeException, match='cannot be opened'):
            lightkurve_cache.fetch_spoc_tpf(search, 0, force_fresh=True)
    assert (cache_root / TPF_REL).read_bytes() == b'old'
    assert not [p for p in os.listdir(cache_root) if p.startswith('.tmp_tpf_')]


def test_fetch_tpf_download_error_is_reported(cache_root):
    search, row, path_patch = _tpf_search(cache_root)
    row.download.side_effect = RuntimeError('504')
    with path_patch, pytest.raises(PipeException, match='504'):
        lightkurve_cache.fetch_spoc_tpf(search, 0)


def _pixel_search(author_names=('TIC 1',)):
    search = mock.MagicMock()
    search.__len__.return_value = 1
    search.target_name = list(author_names)
    return search


def test_download_selected_pixel_ffi_uses_shared_cutout_cache_and_passes_fresh_flag():
    with mock.patch.object(tess_processor, '_restore_pixel_search', return_value=_pixel_search()), \
            mock.patch.object(tess_processor.cache, 'extract_coords', return_value=COORD), \
            mock.patch.object(tess_processor.lightkurve_cache, 'fetch_tesscut_pixel_file',
                              return_value='TPF') as fetch:
        args, data = tess_processor.download_selected_pixel(
            {'#': 0, 'author': 'TESScut'}, {}, 11, fresh_from_mast=True)
    assert data == 'TPF' and args['pixel_type'] == 'FFI'
    assert fetch.call_args.kwargs == {'force_fresh': True}


def test_download_selected_pixel_ffi_fails_when_position_unknown():
    with mock.patch.object(tess_processor, '_restore_pixel_search', return_value=_pixel_search(('nowhere',))), \
            mock.patch.object(tess_processor.cache, 'extract_coords', return_value=None):
        with pytest.raises(PipeException):
            tess_processor.download_selected_pixel({'#': 0, 'author': 'TESScut'}, {}, 11)


def test_download_selected_pixel_tpf_uses_shared_tpf_cache_and_passes_fresh_flag():
    search = _pixel_search()
    with mock.patch.object(tess_processor, '_restore_pixel_search', return_value=search), \
            mock.patch.object(tess_processor.lightkurve_cache, 'fetch_spoc_tpf',
                              return_value='TPF') as fetch:
        args, data = tess_processor.download_selected_pixel(
            {'#': 0, 'author': 'SPOC'}, {}, 11, fresh_from_mast=True)
    assert fetch.call_args.kwargs == {'force_fresh': True}
    assert data == 'TPF' and args['pixel_type'] == 'TPF'


def test_configure_lightkurve_cache_dir_applies_env_variable(tmp_path, monkeypatch):
    target = tmp_path / 'lk'
    monkeypatch.setenv('LIGHTKURVE_CACHE_DIR', str(target))
    with mock.patch.object(lightkurve_cache.lk, 'conf') as conf:
        assert lightkurve_cache.configure_lightkurve_cache_dir() == str(target)
    assert conf.cache_dir == str(target)
    assert target.is_dir()


def test_configure_lightkurve_cache_dir_unset_keeps_library_default(monkeypatch):
    monkeypatch.delenv('LIGHTKURVE_CACHE_DIR', raising=False)
    assert lightkurve_cache.configure_lightkurve_cache_dir() is None


def test_configure_lightkurve_cache_dir_fails_when_not_writable(tmp_path, monkeypatch):
    monkeypatch.setenv('LIGHTKURVE_CACHE_DIR', str(tmp_path))
    with mock.patch.object(lightkurve_cache.os, 'access', return_value=False):
        with pytest.raises(PipeException):
            lightkurve_cache.configure_lightkurve_cache_dir()


def test_delete_cached_handles_fits_entries(tmp_path, monkeypatch):
    monkeypatch.setenv('TESS_CACHE_DIR', str(tmp_path))
    path = tess_cache._get_cache_filename('ffi_data', extension='fits', key='x', size=11)
    open(path, 'wb').write(b'x')
    assert tess_cache.delete_cached('ffi_data', extension='fits', key='x', size=11) is True
    assert tess_cache.delete_cached('ffi_data', extension='fits', key='x', size=11) is False


def test_fresh_pixel_summary_mentions_size_only_for_ffi():
    ffi = tess_processor.fresh_pixel_summary(
        {'target': 'TIC 1', 'mission': 'TESS Sector 30', 'author': 'TESScut', 'exptime': 600}, 11)
    tpf = tess_processor.fresh_pixel_summary(
        {'target': 'TIC 1', 'mission': 'TESS Sector 30', 'author': 'SPOC', 'exptime': 120}, 11)
    assert '11x11 pixels' in ffi and '600 s' in ffi
    assert 'pixels' not in tpf and '120 s' in tpf
