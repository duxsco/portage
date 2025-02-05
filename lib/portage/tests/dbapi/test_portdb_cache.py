# Copyright 2012-2024 Gentoo Authors
# Distributed under the terms of the GNU General Public License v2

import shlex
import shutil
import subprocess
import sys
import textwrap

import portage
from portage import os
from portage import _unicode_decode
from portage.const import BASH_BINARY, PORTAGE_PYM_PATH, USER_CONFIG_PATH
from portage.tests import TestCase
from portage.tests.resolver.ResolverPlayground import ResolverPlayground
from portage.util import ensure_dirs


class PortdbCacheTestCase(TestCase):
    def testPortdbCache(self):
        debug = False

        ebuilds = {
            "dev-libs/A-1": {},
            "dev-libs/A-2": {},
            "sys-apps/B-1": {},
            "sys-apps/B-2": {},
            "sys-apps/C-1": {
                "EAPI": 8,
                "MISC_CONTENT": "inherit bar foo baz",
            },
        }

        # The convoluted structure here is to test accumulation
        # of IDEPEND across eclasses (bug #870295).
        eclasses = {
            "foo": ("inherit bar",),
            "bar": ("IDEPEND=dev-libs/A",),
            "baz": ("IDEPEND=",),
        }

        playground = ResolverPlayground(ebuilds=ebuilds, eclasses=eclasses, debug=debug)
        settings = playground.settings
        eprefix = settings["EPREFIX"]
        test_repo_location = settings.repositories["test_repo"].location
        user_config_dir = os.path.join(eprefix, USER_CONFIG_PATH)
        metadata_dir = os.path.join(test_repo_location, "metadata")
        md5_cache_dir = os.path.join(metadata_dir, "md5-cache")
        pms_cache_dir = os.path.join(metadata_dir, "cache")
        layout_conf_path = os.path.join(metadata_dir, "layout.conf")

        portage_python = portage._python_interpreter
        egencache_cmd = (
            portage_python,
            "-b",
            "-Wd",
            os.path.join(str(self.bindir), "egencache"),
            "--update-manifests",
            "--sign-manifests=n",
            "--repo",
            "test_repo",
            "--repositories-configuration",
            settings.repositories.config_string(),
        )
        python_cmd = (portage_python, "-b", "-Wd", "-c")

        test_commands = (
            (lambda: shutil.rmtree(md5_cache_dir) or True,),
            (lambda: not os.path.exists(pms_cache_dir),),
            (lambda: not os.path.exists(md5_cache_dir),),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				if portage.portdb.repositories['test_repo'].location in portage.portdb._pregen_auxdb:
					sys.exit(1)
			"""
                ),
            ),
            egencache_cmd + ("--update",),
            (lambda: not os.path.exists(pms_cache_dir),),
            (lambda: os.path.exists(md5_cache_dir),),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				if portage.portdb.repositories['test_repo'].location not in portage.portdb._pregen_auxdb:
					sys.exit(1)
			"""
                ),
            ),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				from portage.cache.flat_hash import md5_database
				if not isinstance(portage.portdb._pregen_auxdb[portage.portdb.repositories['test_repo'].location], md5_database):
					sys.exit(1)
			"""
                ),
            ),
            (
                BASH_BINARY,
                "-c",
                "echo %s > %s"
                % tuple(
                    map(
                        shlex.quote,
                        (
                            "cache-formats = md5-dict pms",
                            layout_conf_path,
                        ),
                    )
                ),
            ),
            egencache_cmd + ("--update",),
            (lambda: os.path.exists(md5_cache_dir),),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				if portage.portdb.repositories['test_repo'].location not in portage.portdb._pregen_auxdb:
					sys.exit(1)
			"""
                ),
            ),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				from portage.cache.flat_hash import md5_database
				if not isinstance(portage.portdb._pregen_auxdb[portage.portdb.repositories['test_repo'].location], md5_database):
					sys.exit(1)
			"""
                ),
            ),
            # Disable DeprecationWarnings, since the pms format triggers them
            # in portdbapi._create_pregen_cache().
            (
                BASH_BINARY,
                "-c",
                "echo %s > %s"
                % tuple(
                    map(
                        shlex.quote,
                        (
                            "cache-formats = pms md5-dict",
                            layout_conf_path,
                        ),
                    )
                ),
            ),
            (portage_python, "-b", "-Wd", "-Wi::DeprecationWarning", "-c")
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				if portage.portdb.repositories['test_repo'].location not in portage.portdb._pregen_auxdb:
					sys.exit(1)
			"""
                ),
            ),
            (portage_python, "-b", "-Wd", "-Wi::DeprecationWarning", "-c")
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				from portage.cache.metadata import database as pms_database
				if not isinstance(portage.portdb._pregen_auxdb[portage.portdb.repositories['test_repo'].location], pms_database):
					sys.exit(1)
			"""
                ),
            ),
            (portage_python, "-b", "-Wd", "-Wi::DeprecationWarning", "-c")
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				location = portage.portdb.repositories['test_repo'].location
				if not portage.portdb._pregen_auxdb[location]["sys-apps/C-1"]['IDEPEND']:
					sys.exit(1)
			"""
                ),
            ),
            # Test auto-detection and preference for md5-cache when both
            # cache formats are available but layout.conf is absent.
            (BASH_BINARY, "-c", f"rm {shlex.quote(layout_conf_path)}"),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				if portage.portdb.repositories['test_repo'].location not in portage.portdb._pregen_auxdb:
					sys.exit(1)
			"""
                ),
            ),
            python_cmd
            + (
                textwrap.dedent(
                    """
				import os, sys, portage
				from portage.cache.flat_hash import md5_database
				if not isinstance(portage.portdb._pregen_auxdb[portage.portdb.repositories['test_repo'].location], md5_database):
					sys.exit(1)
			"""
                ),
            ),
        )

        pythonpath = os.environ.get("PYTHONPATH")
        if pythonpath is not None and not pythonpath.strip():
            pythonpath = None
        if pythonpath is not None and pythonpath.split(":")[0] == PORTAGE_PYM_PATH:
            pass
        else:
            if pythonpath is None:
                pythonpath = ""
            else:
                pythonpath = ":" + pythonpath
            pythonpath = PORTAGE_PYM_PATH + pythonpath

        env = {
            "PATH": settings["PATH"],
            "PORTAGE_OVERRIDE_EPREFIX": eprefix,
            "PORTAGE_PYTHON": portage_python,
            "PORTAGE_REPOSITORIES": settings.repositories.config_string(),
            "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE", ""),
            "PYTHONPATH": pythonpath,
        }

        if "__PORTAGE_TEST_HARDLINK_LOCKS" in os.environ:
            env["__PORTAGE_TEST_HARDLINK_LOCKS"] = os.environ[
                "__PORTAGE_TEST_HARDLINK_LOCKS"
            ]

        dirs = [user_config_dir]

        try:
            for d in dirs:
                ensure_dirs(d)

            if debug:
                # The subprocess inherits both stdout and stderr, for
                # debugging purposes.
                stdout = None
            else:
                # The subprocess inherits stderr so that any warnings
                # triggered by python -Wd will be visible.
                stdout = subprocess.PIPE

            for i, args in enumerate(test_commands):
                if hasattr(args[0], "__call__"):
                    self.assertTrue(args[0](), f"callable at index {i} failed")
                    continue

                proc = subprocess.Popen(args, env=env, stdout=stdout)

                if debug:
                    proc.wait()
                else:
                    output = proc.stdout.readlines()
                    proc.wait()
                    proc.stdout.close()
                    if proc.returncode != os.EX_OK:
                        for line in output:
                            sys.stderr.write(_unicode_decode(line))

                self.assertEqual(
                    os.EX_OK,
                    proc.returncode,
                    "command %d failed with args %s"
                    % (
                        i,
                        args,
                    ),
                )
        finally:
            playground.cleanup()
