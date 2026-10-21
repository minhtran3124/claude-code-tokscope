import unittest
import urllib.error

from tokscope import projects, registry


def entry(name, packages=(), remotes=(), latest=True):
    return {"server": {"name": name, "title": name.title(), "description": "Does things.", "version": "1.2.0",
                       "repository": {"url": "https://github.com/x/y"}, "packages": list(packages), "remotes": list(remotes)},
            "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": latest}}}


NPM = {"registryType": "npm", "identifier": "@acme/fs-mcp", "version": "1.2.0", "runtimeHint": "npx",
       "transport": {"type": "stdio"}, "packageArguments": [{"type": "positional", "valueHint": "path", "isRequired": True},
                                                             {"type": "named", "name": "--mode", "value": "ro"}],
       "environmentVariables": [{"name": "ACME_TOKEN", "isSecret": True, "isRequired": True, "description": "API token"},
                                {"name": "ACME_REGION", "default": "eu"}]}
PYPI_FROM = {"registryType": "pypi", "identifier": "acme-ai", "version": "2.0.0", "runtimeHint": "uvx", "transport": {"type": "stdio"},
             "runtimeArguments": [{"type": "named", "name": "--from", "value": "acme-ai==2.0.0"}],
             "packageArguments": [{"type": "positional", "value": "acme"}]}
OCI = {"registryType": "oci", "identifier": "ghcr.io/acme/mcp", "version": "3.1", "transport": {"type": "stdio"},
       "environmentVariables": [{"name": "KEY", "isSecret": True}]}


class RegistryTest(unittest.TestCase):
    def setUp(self):
        registry._cache.clear()

    def search(self, *entries):
        self.urls = []

        def fetch(url):
            self.urls.append(url)
            return {"servers": list(entries), "metadata": {"count": len(entries)}}
        return registry.search("acme", 5, fetch=fetch)

    def test_a_package_becomes_a_command_line_and_a_secret_stays_empty(self):
        (s,) = self.search(entry("io.github.acme/FS Server!", [NPM]))
        self.assertEqual(s["name"], "fs-server")                      # fit for claude mcp add-json
        (o,) = s["options"]
        self.assertEqual((o["transport"], o["command"]), ("stdio", "npx"))
        self.assertEqual(o["args"], ["-y", "@acme/fs-mcp@1.2.0", "<path>", "--mode", "ro"])
        token, region = o["pairs"]
        self.assertEqual((token["key"], token["secret"], token["required"], token["value"]), ("ACME_TOKEN", True, True, ""))
        self.assertEqual(region["value"], "eu")
        self.assertIn("version=latest", self.urls[0])
        self.assertIn("search=acme", self.urls[0])

    def test_uvx_from_and_docker_get_the_right_words(self):
        (s,) = self.search(entry("a/b", [PYPI_FROM, OCI]))
        pypi, oci = s["options"]
        self.assertEqual(pypi["args"], ["--from", "acme-ai==2.0.0", "acme"])   # the package is named once
        self.assertEqual((oci["command"], oci["args"]), ("docker", ["run", "-i", "--rm", "-e", "KEY", "ghcr.io/acme/mcp:3.1"]))

    def test_remotes_keep_header_names_and_unrunnable_ones_drop(self):
        remote = {"type": "streamable-http", "url": "https://mcp.acme.dev/mcp",
                  "headers": [{"name": "Authorization", "isSecret": True, "isRequired": True}]}
        found = self.search(entry("a/remote", remotes=[remote, {"type": "ws", "url": "wss://x"}]),
                            entry("a/nuget-only", [{"registryType": "nuget", "identifier": "X"}]))
        self.assertEqual([s["name"] for s in found], ["remote"])
        (o,) = found[0]["options"]
        self.assertEqual((o["transport"], o["url"], o["pairs"][0]["key"]), ("http", "https://mcp.acme.dev/mcp", "Authorization"))

    def test_every_option_passes_the_add_server_checks(self):
        remote = {"type": "sse", "url": "https://mcp.acme.dev/sse", "headers": [{"name": "X-Key"}]}
        for s in self.search(entry("a/all", [NPM, PYPI_FROM, OCI], [remote])):
            for o in s["options"]:
                form = {"name": s["name"], "scope": "local", **o, "pairs": [{"key": p["key"], "value": "v"} for p in o["pairs"]]}
                projects.build(form)                                   # raises if the registry gave us something odd

    def test_answers_are_cached_and_a_dead_registry_says_so(self):
        self.search(entry("a/b", [NPM]))
        registry.search("acme", 5, fetch=lambda url: self.fail("asked twice"))
        registry._cache.clear()

        def down(url):
            raise urllib.error.URLError("timed out")
        with self.assertRaisesRegex(RuntimeError, "did not answer"):
            registry.search("acme", 5, fetch=down)


if __name__ == "__main__":
    unittest.main()
