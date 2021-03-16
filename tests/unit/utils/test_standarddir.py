# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2014-2021 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <https://www.gnu.org/licenses/>.

"""Tests for qutebrowser.utils.standarddir."""

import os
import pathlib
import sys
import json
import types
import textwrap
import logging
import subprocess

from PyQt5.QtCore import QStandardPaths
import pytest

from qutebrowser.utils import standarddir, utils, qtutils


# Use a different application name for tests to make sure we don't change real
# qutebrowser data if we accidentally access the real path in a test.
APPNAME = 'qute_test'


pytestmark = pytest.mark.usefixtures('qapp')


@pytest.fixture(autouse=True)
def clear_standarddir_cache_and_patch(qapp, monkeypatch):
    """Make sure the standarddir cache is cleared before/after each test.

    Also, patch APPNAME to qute_test.
    """
    assert qapp.applicationName() == APPNAME
    monkeypatch.setattr(standarddir, '_locations', {})
    monkeypatch.setattr(standarddir, 'APPNAME', APPNAME)
    yield
    monkeypatch.setattr(standarddir, '_locations', {})


@pytest.mark.parametrize('orgname, expected', [(None, ''), ('test', 'test')])
def test_unset_organization(qapp, orgname, expected):
    """Test unset_organization.

    Args:
        orgname: The organizationName to set initially.
        expected: The organizationName which is expected when reading back.
    """
    qapp.setOrganizationName(orgname)
    assert qapp.organizationName() == expected  # sanity check
    with standarddir._unset_organization():
        assert qapp.organizationName() == ''
    assert qapp.organizationName() == expected


def test_unset_organization_no_qapp(monkeypatch):
    """Without a QApplication, _unset_organization should do nothing."""
    monkeypatch.setattr(standarddir.QApplication, 'instance', lambda: None)
    with standarddir._unset_organization():
        pass


@pytest.mark.fake_os('mac')
@pytest.mark.posix
def test_fake_mac_config(tmp_path, monkeypatch):
    """Test standardir.config on a fake Mac."""
    monkeypatch.setenv('HOME', str(tmp_path))
    expected = str(tmp_path) + '/.qute_test'  # always with /
    standarddir._init_config(args=None)
    assert standarddir.config() == expected


@pytest.mark.parametrize('what', ['data', 'config', 'cache'])
@pytest.mark.not_mac
@pytest.mark.fake_os('windows')
def test_fake_windows(tmp_path, monkeypatch, what):
    """Make sure the config/data/cache dirs are correct on a fake Windows."""
    monkeypatch.setattr(standarddir.QStandardPaths, 'writableLocation',
                        lambda typ: str(tmp_path / APPNAME))

    standarddir._init_config(args=None)
    standarddir._init_data(args=None)
    standarddir._init_cache(args=None)

    func = getattr(standarddir, what)
    assert func() == str(tmp_path / APPNAME / what)


@pytest.mark.posix
def test_fake_haiku(tmp_path, monkeypatch):
    """Test getting data dir on HaikuOS."""
    locations = {
        QStandardPaths.AppDataLocation: '',
        QStandardPaths.ConfigLocation: str(tmp_path / 'config' / APPNAME),
    }
    monkeypatch.setattr(standarddir.QStandardPaths, 'writableLocation',
                        locations.get)
    monkeypatch.setattr(standarddir.sys, 'platform', 'haiku1')

    standarddir._init_data(args=None)
    assert standarddir.data() == str(tmp_path / 'config' / APPNAME / 'data')


class TestWritableLocation:

    """Tests for _writable_location."""

    def test_empty(self, monkeypatch):
        """Test QStandardPaths returning an empty value."""
        monkeypatch.setattr(
            'qutebrowser.utils.standarddir.QStandardPaths.writableLocation',
            lambda typ: '')
        with pytest.raises(standarddir.EmptyValueError):
            standarddir._writable_location(QStandardPaths.AppDataLocation)

    def test_sep(self, monkeypatch):
        """Make sure the right kind of separator is used."""
        monkeypatch.setattr(standarddir.os, 'sep', '\\')
        monkeypatch.setattr(standarddir.pathlib.Path, 'joinpath',
                            lambda *parts: '\\'.join(parts))
        loc = standarddir._writable_location(QStandardPaths.AppDataLocation)
        assert '/' not in loc
        assert '\\' in loc


class TestStandardDir:

    @pytest.mark.parametrize('func, init_func, varname', [
        (standarddir.data, standarddir._init_data, 'XDG_DATA_HOME'),
        (standarddir.config, standarddir._init_config, 'XDG_CONFIG_HOME'),
        (lambda: standarddir.config(auto=True),
         standarddir._init_config, 'XDG_CONFIG_HOME'),
        (standarddir.cache, standarddir._init_cache, 'XDG_CACHE_HOME'),
        (standarddir.runtime, standarddir._init_runtime, 'XDG_RUNTIME_DIR'),
    ])
    @pytest.mark.linux
    def test_linux_explicit(self, monkeypatch, tmp_path,
                            func, init_func, varname):
        """Test dirs with XDG environment variables explicitly set.

        Args:
            func: The function to test.
            init_func: The initialization function to call.
            varname: The environment variable which should be set.
        """
        monkeypatch.setenv(varname, str(tmp_path))
        if varname == 'XDG_RUNTIME_DIR':
            tmp_path.chmod(0o0700)

        init_func(args=None)
        assert func() == str(tmp_path / APPNAME)

    @pytest.mark.parametrize('func, subdirs', [
        (standarddir.data, ['.local', 'share', APPNAME]),
        (standarddir.config, ['.config', APPNAME]),
        (lambda: standarddir.config(auto=True), ['.config', APPNAME]),
        (standarddir.cache, ['.cache', APPNAME]),
        (standarddir.download, ['Downloads']),
    ])
    @pytest.mark.linux
    def test_linux_normal(self, monkeypatch, tmp_path, func, subdirs):
        """Test dirs with XDG_*_HOME not set."""
        monkeypatch.setenv('HOME', str(tmp_path))
        for var in ['DATA', 'CONFIG', 'CACHE']:
            monkeypatch.delenv('XDG_{}_HOME'.format(var), raising=False)
        standarddir._init_dirs()
        assert func() == str(tmp_path.joinpath(*subdirs))

    @pytest.mark.linux
    @pytest.mark.qt_log_ignore(r'^QStandardPaths: ')
    @pytest.mark.skipif(
        qtutils.version_check('5.14', compiled=False),
        reason="Qt 5.14 automatically creates missing runtime dirs")
    def test_linux_invalid_runtimedir(self, monkeypatch, tmp_path):
        """With invalid XDG_RUNTIME_DIR, fall back to TempLocation."""
        tmp_path_env = tmp_path / 'temp'
        tmp_path_env.mkdir(exist_ok=True)
        monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'does-not-exist'))
        monkeypatch.setenv('TMPDIR', str(tmp_path_env))

        standarddir._init_runtime(args=None)
        assert standarddir.runtime() == str(tmp_path_env / APPNAME)

    @pytest.mark.fake_os('windows')
    def test_runtimedir_empty_tempdir(self, monkeypatch, tmp_path):
        """With an empty tempdir on non-Linux, we should raise."""
        monkeypatch.setattr(standarddir.QStandardPaths, 'writableLocation',
                            lambda typ: '')
        with pytest.raises(standarddir.EmptyValueError):
            standarddir._init_runtime(args=None)

    @pytest.mark.parametrize('func, elems, expected', [
        (standarddir.data, 2, [APPNAME, 'data']),
        (standarddir.config, 2, [APPNAME, 'config']),
        (lambda: standarddir.config(auto=True), 2, [APPNAME, 'config']),
        (standarddir.cache, 2, [APPNAME, 'cache']),
        (standarddir.download, 1, ['Downloads']),
    ])
    @pytest.mark.windows
    def test_windows(self, func, elems, expected):
        standarddir._init_dirs()
        assert func().split(os.sep)[-elems:] == expected

    @pytest.mark.parametrize('func, elems, expected', [
        (standarddir.data, 2, ['Application Support', APPNAME]),
        (lambda: standarddir.config(auto=True), 1, [APPNAME]),
        (standarddir.config, 0,
         str(pathlib.Path('~').expanduser()).split(os.sep) + ['.qute_test']),
        (standarddir.cache, 2, ['Caches', APPNAME]),
        (standarddir.download, 1, ['Downloads']),
    ])
    @pytest.mark.mac
    def test_mac(self, func, elems, expected):
        standarddir._init_dirs()
        assert func().split(os.sep)[-elems:] == expected


class TestArguments:

    """Tests the --basedir argument."""

    @pytest.mark.parametrize('typ, args', [
        ('config', []),
        ('config', [True]),  # user config
        ('data', []),
        ('cache', []),
        ('download', []),
        pytest.param('runtime', [], marks=pytest.mark.linux)])
    def test_basedir(self, tmp_path, typ, args):
        """Test --basedir."""
        expected = str(tmp_path / typ)
        init_args = types.SimpleNamespace(basedir=str(tmp_path))
        standarddir._init_dirs(init_args)
        func = getattr(standarddir, typ)
        assert func(*args) == expected

    def test_basedir_relative(self, tmp_path):
        """Test --basedir with a relative path."""
        basedir = (tmp_path / 'basedir')
        basedir.mkdir(exist_ok=True)
        os.chdir(tmp_path)
        args = types.SimpleNamespace(basedir='basedir')
        standarddir._init_dirs(args)
        assert standarddir.config() == str(basedir / 'config')

    def test_config_py_arg(self, tmp_path):
        basedir = tmp_path / 'basedir'
        basedir.mkdir(exist_ok=True)
        os.chdir(tmp_path)
        args = types.SimpleNamespace(
            basedir='foo', config_py='basedir/config.py')
        standarddir._init_dirs(args)
        assert standarddir.config_py() == str(basedir / 'config.py')

    def test_config_py_no_arg(self, tmp_path):
        basedir = tmp_path / 'basedir'
        basedir.mkdir(exist_ok=True)
        os.chdir(tmp_path)
        args = types.SimpleNamespace(basedir='basedir')
        standarddir._init_dirs(args)
        assert standarddir.config_py() == str(
            basedir / 'config' / 'config.py')


class TestInitCacheDirTag:

    """Tests for _init_cachedir_tag."""

    def test_existent_cache_dir_tag(self, tmp_path, mocker, monkeypatch):
        """Test with an existent CACHEDIR.TAG."""
        monkeypatch.setattr(standarddir, 'cache', lambda: str(tmp_path))
        mocker.patch('pathlib.Path.open', side_effect=AssertionError)
        m = mocker.patch('qutebrowser.utils.standarddir.pathlib.Path')
        m.exists.return_value = True
        standarddir._init_cachedir_tag()
        assert not list(tmp_path.iterdir())
        m.assert_called_with(str(tmp_path))

    def test_new_cache_dir_tag(self, tmp_path, mocker, monkeypatch):
        """Test creating a new CACHEDIR.TAG."""
        monkeypatch.setattr(standarddir, 'cache', lambda: str(tmp_path))
        standarddir._init_cachedir_tag()
        for x in tmp_path.iterdir():
            assert x == tmp_path / 'CACHEDIR.TAG'
        data = (tmp_path / 'CACHEDIR.TAG').read_text('utf-8')
        assert data == textwrap.dedent("""
            Signature: 8a477f597d28d172789f06886806bc55
            # This file is a cache directory tag created by qutebrowser.
            # For information about cache directory tags, see:
            #  https://bford.info/cachedir/
        """).lstrip()

    def test_open_oserror(self, caplog, unwritable_tmp_path, monkeypatch):
        """Test creating a new CACHEDIR.TAG."""
        monkeypatch.setattr(standarddir, 'cache', lambda: str(unwritable_tmp_path))
        with caplog.at_level(logging.ERROR, 'init'):
            standarddir._init_cachedir_tag()
        assert caplog.messages == ['Failed to create CACHEDIR.TAG']


class TestCreatingDir:

    """Make sure inexistent directories are created properly."""

    DIR_TYPES = ['config', 'data', 'cache', 'download', 'runtime']

    @pytest.mark.parametrize('typ', DIR_TYPES)
    def test_basedir(self, tmp_path, typ):
        """Test --basedir."""
        basedir = tmp_path / 'basedir'
        assert not basedir.exists()

        args = types.SimpleNamespace(basedir=str(basedir))
        standarddir._init_dirs(args)

        func = getattr(standarddir, typ)
        func()

        assert basedir.exists()

        if typ == 'download' or (typ == 'runtime' and not utils.is_linux):
            assert not (basedir / typ).exists()
        else:
            assert (basedir / typ).exists()

            if utils.is_posix:
                assert (basedir / typ).stat().st_mode & 0o777 == 0o700

    @pytest.mark.parametrize('typ', DIR_TYPES)
    def test_exists_race_condition(self, mocker, tmp_path, typ):
        """Make sure there can't be a TOCTOU issue when creating the file.

        See https://github.com/qutebrowser/qutebrowser/issues/942.
        """
        (tmp_path / typ).mkdir(exist_ok=True)

        m = mocker.patch('qutebrowser.utils.standarddir.pathlib')
        m.Path.mkdir = pathlib.Path.mkdir
        m.sep = '/'
        m.Path.joinpath = pathlib.Path.joinpath
        m.Path.expanduser = pathlib.Path.expanduser
        m.Path.exists.return_value = False
        m.Path.resolve = lambda x: x

        args = types.SimpleNamespace(basedir=str(tmp_path))
        standarddir._init_dirs(args)

        func = getattr(standarddir, typ)
        func()


class TestSystemData:

    """Test system data path."""

    @pytest.mark.linux
    def test_system_datadir_exist_linux(self, monkeypatch, tmp_path):
        """Test that /usr/share/qute_test is used if path exists."""
        monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
        monkeypatch.setattr(pathlib.Path, 'exists', lambda path: True)
        standarddir._init_data(args=None)
        assert standarddir.data(system=True) == "/usr/share/qute_test"

    @pytest.mark.linux
    def test_system_datadir_not_exist_linux(self, monkeypatch, tmp_path,
                                            fake_args):
        """Test that system-wide path isn't used on linux if path not exist."""
        fake_args.basedir = str(tmp_path)
        monkeypatch.setattr(pathlib.Path, 'exists', lambda path: False)
        standarddir._init_data(args=fake_args)
        assert standarddir.data(system=True) == standarddir.data()

    def test_system_datadir_unsupportedos(self, monkeypatch, tmp_path,
                                          fake_args):
        """Test that system-wide path is not used on non-Linux OS."""
        fake_args.basedir = str(tmp_path)
        monkeypatch.setattr(sys, 'platform', 'potato')
        standarddir._init_data(args=fake_args)
        assert standarddir.data(system=True) == standarddir.data()


@pytest.mark.parametrize('args_kind', ['basedir', 'normal', 'none'])
def test_init(tmp_path, monkeypatch, args_kind):
    """Do some sanity checks for standarddir.init().

    Things like _init_cachedir_tag() are tested in more detail in other tests.
    """
    assert standarddir._locations == {}

    monkeypatch.setenv('HOME', str(tmp_path))

    if args_kind == 'normal':
        args = types.SimpleNamespace(basedir=None)
    elif args_kind == 'basedir':
        args = types.SimpleNamespace(basedir=str(tmp_path))
    else:
        assert args_kind == 'none'
        args = None

    standarddir.init(args)

    assert standarddir._locations != {}


@pytest.mark.linux
def test_downloads_dir_not_created(monkeypatch, tmp_path):
    """Make sure ~/Downloads is not created."""
    download_dir = tmp_path / 'Downloads'
    monkeypatch.setenv('HOME', str(tmp_path))
    # Make sure xdg-user-dirs.dirs is not picked up
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    standarddir._init_dirs()
    assert standarddir.download() == str(download_dir)
    assert not download_dir.exists()


def test_no_qapplication(qapp, tmp_path, monkeypatch):
    """Make sure directories with/without QApplication are equal."""
    sub_code = """
        import sys
        import json

        sys.path = sys.argv[1:]  # make sure we have the same python path

        from PyQt5.QtWidgets import QApplication
        from qutebrowser.utils import standarddir

        assert QApplication.instance() is None

        standarddir.APPNAME = 'qute_test'
        standarddir._init_dirs()

        locations = {k.name: v for k, v in standarddir._locations.items()}
        print(json.dumps(locations))
    """
    pyfile = tmp_path / 'sub.py'
    pyfile.write_text(textwrap.dedent(sub_code), encoding='ascii')

    for name in ['CONFIG', 'DATA', 'CACHE']:
        monkeypatch.delenv('XDG_{}_HOME'.format(name), raising=False)

    runtime_dir = tmp_path / 'runtime'
    runtime_dir.mkdir(exist_ok=True)
    runtime_dir.chmod(0o0700)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(runtime_dir))

    home_dir = tmp_path / 'home'
    home_dir.mkdir(exist_ok=True)
    monkeypatch.setenv('HOME', str(home_dir))

    proc = subprocess.run([sys.executable, str(pyfile)] + sys.path,
                          universal_newlines=True,
                          check=True,
                          stdout=subprocess.PIPE)
    sub_locations = json.loads(proc.stdout)

    standarddir._init_dirs()
    locations = {k.name: v for k, v in standarddir._locations.items()}

    assert sub_locations == locations
