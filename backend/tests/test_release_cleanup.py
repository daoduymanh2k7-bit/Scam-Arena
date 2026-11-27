import importlib.util
import os
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('release_cleanup',Path(__file__).resolve().parents[2]/'deployment/cleanup_releases.py')
cleanup=importlib.util.module_from_spec(spec);spec.loader.exec_module(cleanup)


def fixtures(tmp_path):
    archives=tmp_path/'archives';releases=tmp_path/'releases';archives.mkdir();releases.mkdir()
    for i in range(6):
        sha=f'{i:040x}';folder=releases/sha;folder.mkdir();(folder/'Dockerfile').write_text('source')
        archive=archives/f'scam-arena-{sha}.tar.gz';archive.write_bytes(b'package')
        os.utime(folder,(100+i,100+i));os.utime(archive,(100+i,100+i))
    return archives,releases


def test_retains_active_old_revision_and_three_newest(tmp_path):
    archives,releases=fixtures(tmp_path);active=f'{0:040x}'
    victims,protected=cleanup.plan(archives,releases,active)
    assert len(victims)==4 and active in protected
    assert {p.name for p in victims if p.is_dir()}=={f'{1:040x}',f'{2:040x}'}
    for path in victims:cleanup.remove(path,archives,releases)
    assert (releases/active).exists() and len(list(releases.iterdir()))==4


def test_preserves_unknown_files_credentials_and_container_mounts(tmp_path):
    archives,releases=fixtures(tmp_path)
    (archives/'database.dump').write_text('backup');(releases/'manual-install').mkdir()
    (releases/f'{1:040x}'/'.env').write_text('private')
    mounted=releases/f'{2:040x}'/'data';mounted.mkdir()
    victims,_=cleanup.plan(archives,releases,f'{0:040x}',mounts=[mounted])
    assert releases/f'{1:040x}' not in victims
    assert releases/f'{2:040x}' not in victims
    assert archives/'database.dump' not in victims
    assert releases/'manual-install' not in victims


def test_missing_revision_and_escaping_paths_fail_closed(tmp_path):
    archives,releases=fixtures(tmp_path)
    with pytest.raises(ValueError):cleanup.plan(archives,releases,'')
    with pytest.raises(ValueError):cleanup.remove(tmp_path,archives,releases)
    with pytest.raises(ValueError):cleanup.remove(releases,archives,releases)
    with pytest.raises(ValueError):cleanup.plan(archives,releases,f'{0:040x}',keep=1)
