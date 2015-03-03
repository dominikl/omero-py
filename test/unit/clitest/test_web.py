#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
# Copyright (C) 2015 University of Dundee & Open Microscopy Environment.
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import pytest
from difflib import unified_diff
import re
from path import path
import omero.cli
from omero.plugins.web import WebControl
from omeroweb import settings


class TestWeb(object):

    def setup_method(self, method):
        self.cli = omero.cli.CLI()
        self.cli.register("web", WebControl, "TEST")
        self.args = ["web"]

    def set_templates_dir(self, monkeypatch):

        dist_dir = path(__file__) / ".." / ".." / ".." / ".." / ".." / ".." /\
            ".." / "dist"  # FIXME: should not be hard-coded
        dist_dir = dist_dir.abspath()
        monkeypatch.setattr(WebControl, '_get_templates_dir',
                            lambda x: dist_dir / "etc" / "templates")

    def add_prefix(self, prefix, monkeypatch):

        def _get_default_value(x):
            return settings.CUSTOM_SETTINGS_MAPPINGS[x][1]
        if prefix:
            static_prefix = prefix + '-static/'
        else:
            prefix = _get_default_value('omero.web.prefix')
            static_prefix = _get_default_value('omero.web.static_url')
        monkeypatch.setattr(settings, 'STATIC_URL', static_prefix,
                            raising=False)
        monkeypatch.setattr(settings, 'FORCE_SCRIPT_NAME', prefix,
                            raising=False)
        return static_prefix

    def clean_generated_file(self, txt):
        assert "%(" not in txt   # Make sure all markers have been replaced
        lines = [line.strip() for line in txt.split('\n')]
        lines = [line for line in lines if line and not line.startswith('#')]
        return lines

    def required_lines_in(self, required, lines):
        # Checks that all lines in required are present in the same order,
        # but not necessarily consecutively
        def compare(req, line):
            if isinstance(req, tuple):
                return line.startswith(req[0]) and line.endswith(req[1])
            return req == line

        n = 0
        for req in required:
            if not compare(req, lines[n]):
                n += 1
                if n == len(lines):
                    return req
        return None

    def normalise_generated(self, s):
        serverdir = self.cli.dir
        s = re.sub('\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.\d{6}',
                   '0000-00-00 00:00:00.000000', s)
        s = s.replace(serverdir, '/home/omero/OMERO.server')
        return s

    def compare_with_reference(self, refname, generated):
        reffile = path(__file__).dirname() / 'reference_templates' / refname
        generated = generated.split('\n')
        # reffile.write_lines(generated)
        ref = reffile.lines(retain=False)
        d = '\n'.join(unified_diff(ref, generated))
        return d

    def testHelp(self):
        self.args += ["-h"]
        self.cli.invoke(self.args, strict=True)

    @pytest.mark.parametrize('subcommand', WebControl().get_subcommands())
    def testSubcommandHelp(self, subcommand):
        self.args += [subcommand, "-h"]
        self.cli.invoke(self.args, strict=True)

    @pytest.mark.parametrize('max_body_size', [None, '0', '1m'])
    @pytest.mark.parametrize('server_type', [
        "nginx", "nginx-development", "nginx --system"])
    @pytest.mark.parametrize('http', [False, 8081])
    @pytest.mark.parametrize('prefix', [None, '/test'])
    def testNginxConfig(self, server_type, http, prefix, capsys, monkeypatch,
                        max_body_size):

        static_prefix = self.add_prefix(prefix, monkeypatch)
        self.args += ["config"]
        self.args += server_type.split()
        if http:
            self.args += ["--http", str(http)]
        if max_body_size:
            self.args += ["--max-body-size", max_body_size]
        self.set_templates_dir(monkeypatch)
        self.cli.invoke(self.args, strict=True)
        o, e = capsys.readouterr()
        lines = self.clean_generated_file(o)

        if server_type.split()[0] == "nginx":
            missing = self.required_lines_in([
                "server {",
                "listen       %s;" % (http or 80),
                "client_max_body_size %s;" % (max_body_size or '0'),
                "location %s {" % static_prefix[:-1],
                "location %s {" % (prefix or "/"),
                ], lines)
        else:
            missing = self.required_lines_in([
                "server {",
                "listen       %s;" % (http or 8080),
                "client_max_body_size %s;" % (max_body_size or '0'),
                "location %s {" % static_prefix[:-1],
                "location %s {" % (prefix or "/"),
                ], lines)
        assert not missing, 'Line not found: ' + missing

    @pytest.mark.parametrize('prefix', [None, '/test'])
    def testApacheConfig(self, prefix, capsys, monkeypatch):

        static_prefix = self.add_prefix(prefix, monkeypatch)
        self.args += ["config", "apache"]
        self.set_templates_dir(monkeypatch)
        self.cli.invoke(self.args, strict=True)
        o, e = capsys.readouterr()

        lines = self.clean_generated_file(o)

        if prefix:
            missing = self.required_lines_in([
                'RewriteEngine on',
                'RewriteRule ^/?$ %s/ [R]' % prefix,
                ('FastCGIExternalServer ',
                 'var/omero.fcgi" -host 0.0.0.0:4080 -idle-timeout 60'),
                ('Alias %s ' % static_prefix[:-1],
                 'lib/python/omeroweb/static'),
                ('Alias %s "' % prefix, 'var/omero.fcgi/"'),
                ], lines)
        else:
            missing = self.required_lines_in([
                ('FastCGIExternalServer ',
                 'var/omero.fcgi" -host 0.0.0.0:4080 -idle-timeout 60'),
                ('Alias /static ', 'lib/python/omeroweb/static'),
                ('Alias / "', 'var/omero.fcgi/"'),
                ], lines)
        assert not missing, 'Line not found: ' + missing

    @pytest.mark.parametrize('prefix', [None, '/test'])
    def testApacheFcgiConfig(self, prefix, capsys, monkeypatch):

        static_prefix = self.add_prefix(prefix, monkeypatch)
        self.args += ["config", "apache-fcgi"]
        self.set_templates_dir(monkeypatch)
        self.cli.invoke(self.args, strict=True)
        o, e = capsys.readouterr()

        lines = self.clean_generated_file(o)

        if prefix:
            missing = self.required_lines_in([
                ('Alias %s' % static_prefix[:-1],
                 'lib/python/omeroweb/static'),
                'RewriteCond %%{REQUEST_URI} !^(%s|/\\.fcgi)' %
                static_prefix[:-1],
                'RewriteRule ^%s(/|$)(.*) %s.fcgi/$2 [PT]' % (prefix, prefix),
                'SetEnvIf Request_URI . proxy-fcgi-pathinfo=1',
                'ProxyPass %s.fcgi/ fcgi://0.0.0.0:4080/' % prefix,
                ], lines)
        else:
            missing = self.required_lines_in([
                ('Alias /static ', 'lib/python/omeroweb/static'),
                'RewriteCond %%{REQUEST_URI} !^(/static|/\\.fcgi)',
                'RewriteRule ^(/|$)(.*) /.fcgi/$2 [PT]',
                'SetEnvIf Request_URI . proxy-fcgi-pathinfo=1',
                'ProxyPass /.fcgi/ fcgi://0.0.0.0:4080/',
                ], lines)
        assert not missing, 'Line not found: ' + missing

    @pytest.mark.parametrize('server_type', [
        "nginx", "nginx-development", "apache", "apache-fcgi"])
    def testFullTemplateDefaults(self, server_type, capsys, monkeypatch):
        self.args += ["config", server_type]
        self.set_templates_dir(monkeypatch)
        self.cli.invoke(self.args, strict=True)

        o, e = capsys.readouterr()
        assert not e
        o = self.normalise_generated(o)
        d = self.compare_with_reference(server_type + '.conf', o)
        assert not d, 'Files are different:\n' + d

    @pytest.mark.parametrize('server_type', [
        ['nginx', '--http', '1234', '--max-body-size', '2m'],
        ['nginx-development', '--http', '1234', '--max-body-size', '2m'],
        ['apache'],
        ['apache-fcgi']])
    def testFullTemplateWithOptions(self, server_type, capsys, monkeypatch):
        prefix = '/test'
        self.add_prefix(prefix, monkeypatch)
        self.args += ["config"] + server_type
        self.set_templates_dir(monkeypatch)
        self.cli.invoke(self.args, strict=True)

        o, e = capsys.readouterr()
        assert not e
        o = self.normalise_generated(o)
        d = self.compare_with_reference(
            server_type[0] + '-withoptions.conf', o)
        assert not d, 'Files are different:\n' + d