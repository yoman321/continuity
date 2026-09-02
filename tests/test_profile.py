"""The wiki profile — the seam that keeps one wiki's conventions out of the core.

The point of these tests is not that each profile holds the right values; it is that the
*same input* produces different, correct answers under two profiles. With one profile every
hardcoded assumption still passes its own tests (`summary.md` §5).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.ledger.schema import Source
from backend.core.ledger.tiers import UNKNOWN_TIER
from backend.core.profile import MCU_FANDOM, PROFILES, WIKIPEDIA_EN, local_wiki

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


class TestTitleGrammar(unittest.TestCase):
    def test_fandom_splits_a_variant_subpage(self) -> None:
        ref = MCU_FANDOM.entity_ref("Human Torch/Void-Analyzing Fantastic Four")
        self.assertTrue(ref.is_variant)
        self.assertEqual(ref.base, "Human Torch")
        self.assertEqual(ref.variant, "Void-Analyzing Fantastic Four")

    def test_wikipedia_does_not_split_a_slash_in_a_title(self) -> None:
        """`AC/DC` is one 202KB article. Splitting it invents a subject called `AC`."""
        ref = WIKIPEDIA_EN.entity_ref("AC/DC")
        self.assertFalse(ref.is_variant)
        self.assertEqual(ref.base, "AC/DC")
        self.assertIsNone(ref.variant)

    def test_the_same_title_parses_differently_per_wiki(self) -> None:
        """The whole reason the profile exists — one input, two correct answers."""
        self.assertTrue(MCU_FANDOM.entity_ref("Face/Off").is_variant)
        self.assertFalse(WIKIPEDIA_EN.entity_ref("Face/Off").is_variant)

    def test_a_title_without_a_slash_is_never_a_variant(self) -> None:
        for profile in (MCU_FANDOM, WIKIPEDIA_EN):
            with self.subTest(profile=profile.name):
                self.assertFalse(profile.entity_ref("Gambit").is_variant)


class TestSourceTiers(unittest.TestCase):
    def test_the_same_url_tiers_differently_per_wiki(self) -> None:
        """A studio press release is primary on the fan wiki and interested on Wikipedia."""
        url = "https://marvel.com/announcement"
        fandom = Source.create(url, "…", NOW, domain_tiers=MCU_FANDOM.domain_tiers)
        wiki = Source.create(url, "…", NOW, domain_tiers=WIKIPEDIA_EN.domain_tiers)
        self.assertEqual(fandom.tier, 1)
        self.assertEqual(wiki.tier, 4)

    def test_domain_is_resolved_once_and_stored(self) -> None:
        src = Source.create("https://www.deadline.com/x", "…", NOW,
                            domain_tiers=MCU_FANDOM.domain_tiers)
        self.assertEqual(src.domain, "deadline.com")

    def test_a_domain_absent_from_the_table_is_not_a_guess(self) -> None:
        src = Source.create("https://bfi.org.uk/x", "…", NOW,
                            domain_tiers=MCU_FANDOM.domain_tiers)
        self.assertEqual(src.tier, UNKNOWN_TIER)
        # ...but it is tier 1 on the wiki whose table knows it.
        other = Source.create("https://bfi.org.uk/x", "…", NOW,
                              domain_tiers=WIKIPEDIA_EN.domain_tiers)
        self.assertEqual(other.tier, 1)


class TestRetrievalPolicy(unittest.TestCase):
    def test_include_domains_is_the_tier_1_to_3_slice(self) -> None:
        """`AGENTS.md` §7: the tier table is the retrieval filter, not only the score."""
        for profile in (MCU_FANDOM, WIKIPEDIA_EN):
            with self.subTest(profile=profile.name):
                allowed = set(profile.include_domains)
                self.assertTrue(allowed)
                for domain, tier in profile.domain_tiers.items():
                    self.assertEqual(domain in allowed, tier <= 3)

    def test_no_fan_wiki_is_ever_an_allowed_source(self) -> None:
        for profile in (MCU_FANDOM, WIKIPEDIA_EN):
            with self.subTest(profile=profile.name):
                self.assertNotIn("fandom.com", profile.include_domains)
                self.assertNotIn("wikipedia.org", profile.include_domains)


class TestSectionVocabulary(unittest.TestCase):
    def test_mcu_wiki_has_no_box_office_and_wikipedia_does(self) -> None:
        """`summary.md` §8: dropping box office is a scope decision read off the wiki."""
        self.assertFalse(MCU_FANDOM.has_section("Box office"))
        self.assertTrue(WIKIPEDIA_EN.has_section("Box office"))

    def test_the_seed_corpus_headings_are_all_in_the_vocabulary(self) -> None:
        """The vocabulary was read off `snapshots/seed/`; keep it that way."""
        seed = Path(__file__).resolve().parents[1] / "snapshots" / "seed"
        headings = {
            line.strip().strip("=").strip()
            for path in seed.glob("*.wikitext")
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("==") and not line.startswith("===")
        }
        unknown = {h for h in headings if h and not MCU_FANDOM.has_section(h)}
        self.assertEqual(unknown, set(), f"headings missing from the profile: {sorted(unknown)}")


class TestDependencyDirection(unittest.TestCase):
    def test_the_core_does_not_import_the_profile_at_runtime(self) -> None:
        """`AGENTS.md` §2: `profile/` imports the core, never the reverse.

        Asserted rather than agreed, for the same reason the cold-start rule is asserted — an
        import direction inverts by accident during a refactor and nothing complains. A
        `TYPE_CHECKING` reference is fine and invisible here; an unguarded one is not.
        """
        root = str(Path(__file__).resolve().parents[1])
        code = (
            "import sys; import backend.core.ledger, backend.core.wiki; "
            "sys.exit(1 if any(m.startswith('backend.core.profile') for m in sys.modules) else 0)"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True)
        self.assertEqual(result.returncode, 0,
                         "backend.core.profile was imported by the ledger/wiki core")


    def test_the_backend_package_root_imports_nothing(self) -> None:
        """`backend/__init__.py` runs before every `backend.core.*` import.

        A vendor import there would make the dependency-free core silently require the SDKs,
        and would defeat the cold-start deferral in `app.py`. Cheaper to assert than to
        rediscover on a cold container.
        """
        root = Path(__file__).resolve().parents[1] / "backend" / "__init__.py"
        code = [
            line for line in root.read_text().splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        self.assertEqual(code, [], f"backend/__init__.py must stay import-free, found: {code}")


class TestWritePolicy(unittest.TestCase):
    def test_no_shipped_profile_is_writable(self) -> None:
        """`AGENTS.md` §2: never write to any real wiki. Encoded, not just written down."""
        for name, profile in PROFILES.items():
            with self.subTest(profile=name):
                self.assertFalse(profile.writable)


if __name__ == "__main__":
    unittest.main()


class TestLocalWiki(unittest.TestCase):
    """Our own instance, and the two things that make it different from the wikis we read.

    `AGENTS.md` §2 forbids writing to any real wiki, and the endpoint of our own is a
    deployment identifier that `.env` owns exclusively. Both show up here as properties of the
    profile rather than as prose someone has to remember.
    """

    def test_it_is_the_only_writable_profile(self) -> None:
        self.assertTrue(local_wiki("http://example.invalid/api.php").writable)
        for name, profile in PROFILES.items():
            self.assertFalse(profile.writable, f"{name} must not be writable")

    def test_the_endpoint_is_injected_and_never_hardcoded(self) -> None:
        """A factory with no default, not a constant.

        `AGENTS.md` §2 keeps the *value* of a deployment identifier in `.env` alone; naming the
        variable is fine and `README.md` does it. So this asserts two things about the value:
        no caller can get an endpoint without supplying one, and no host of ours is written
        down here.
        """
        import inspect

        api_url = inspect.signature(local_wiki).parameters["api_url"]
        self.assertIs(api_url.default, inspect.Parameter.empty)

        known = Path(__file__).resolve().parents[1] / "backend/core/profile/known.py"
        source = known.read_text("utf-8")
        for host in ("localhost", "127.0.0.1", "0.0.0.0", ".internal", "ngrok"):
            self.assertNotIn(host, source)
        self.assertEqual(local_wiki("http://x/api.php").api_url, "http://x/api.php")

    def test_it_inherits_the_grammar_of_the_wiki_it_is_seeded_from(self) -> None:
        """It holds `snapshots/seed/`, so it must parse those titles the way Fandom does —
        otherwise a variant subpage stops being a variant halfway through the pipeline."""
        local = local_wiki("http://x/api.php")
        self.assertEqual(local.subpages, MCU_FANDOM.subpages)
        self.assertEqual(local.section_vocabulary, MCU_FANDOM.section_vocabulary)
        self.assertEqual(local.licence, MCU_FANDOM.licence)
        self.assertEqual(
            local.entity_ref("Blade/Universe Defender Blade"),
            MCU_FANDOM.entity_ref("Blade/Universe Defender Blade"),
        )


class TestNothingSourceIsIgnored(unittest.TestCase):
    """No source file may be excluded from a commit by `.gitignore`.

    This exists because it happened. A `wiki/` entry added for the local MediaWiki install
    matched *any* directory named wiki at any depth, including `backend/core/wiki/` — and
    because the other files there were already tracked, only the newest one disappeared. The
    package would have been committed half-built, and the failure would have surfaced on
    someone else's clone rather than here. `.gitignore` directory patterns are anchored now,
    and this asserts it stays that way.
    """

    def ignored(self, paths: list[str]) -> list[str]:
        import shutil
        import subprocess

        if shutil.which("git") is None:  # pragma: no cover - git is present in this repo
            raise unittest.SkipTest("needs git")
        root = Path(__file__).resolve().parents[1]
        # These assert a property of *this repository's* ignore rules, so they are meaningless
        # outside a work tree — a copied tree, or a source tarball, has no rules to check.
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root, capture_output=True, text=True,
        )
        if inside.returncode != 0:  # pragma: no cover - only outside a checkout
            raise unittest.SkipTest("not a git work tree")
        # `check-ignore` exits 1 when nothing matches, which is the good case.
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(paths), cwd=root, capture_output=True, text=True,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]

    def test_no_python_source_is_ignored(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sources = [
            str(p.relative_to(root))
            for folder in ("backend", "tests", "scripts")
            for p in (root / folder).rglob("*.py")
            if "__pycache__" not in p.parts
        ]
        self.assertGreater(len(sources), 20, "found suspiciously few source files")
        self.assertEqual(self.ignored(sources), [])

    def test_the_committed_config_and_scripts_are_not_ignored(self) -> None:
        wanted = [
            "scripts/mongo.sh",
            "snapshots/manifest.json",
            "snapshots/wiki-db.dummy.json",
            "FE/data/wiki-db.json",
            "pyproject.toml",
            ".env.example",
        ]
        self.assertEqual(self.ignored(wanted), [])

    def test_the_things_that_must_stay_out_really_are_out(self) -> None:
        """The other half: anchoring the patterns must not have unignored the install."""
        self.assertEqual(
            sorted(self.ignored([".env", "wiki/LocalSettings.php", "fixtures/searches.json"])),
            [".env", "fixtures/searches.json", "wiki/LocalSettings.php"],
        )
