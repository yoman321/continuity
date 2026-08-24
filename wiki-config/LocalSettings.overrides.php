<?php
/**
 * Continuity's overrides on top of the generated LocalSettings.php.
 *
 * `LocalSettings.php` is written by the installer and lives in the gitignored `wiki/` tree, so
 * it is a build artifact. Everything we actually decided lives here instead, in version
 * control, and the installer's output just requires this file at the end.
 *
 * Every setting below exists to make this instance answer like the wiki it is seeded from.
 * `snapshots/seed/` is 12 pages of MCU Fandom, and the agent parses their titles and headings
 * through `MCU_FANDOM`'s grammar — so if this instance disagreed with that grammar, the
 * profile would be describing a wiki that no longer exists.
 */

if ( !defined( 'MEDIAWIKI' ) ) {
	exit;
}

/**
 * Mainspace subpages, because Fandom enables them and Wikipedia does not.
 *
 * This is the single most load-bearing line in the file. It is what makes
 * `Human Torch/Void-Analyzing Fantastic Four` a subpage of `Human Torch` rather than an
 * article with a slash in its name, and `WikiProfile.subpages` is the agent's model of exactly
 * this setting. MediaWiki reports it through `siprop=namespaces`, so the two can be compared
 * rather than assumed — `scripts/seed_wiki.py --check` does that.
 */
$wgNamespacesWithSubpages[NS_MAIN] = true;

/**
 * CC BY-SA 3.0, matching the seed corpus rather than MediaWiki's default.
 *
 * Share-alike carries onto a copy (`snapshots/ATTRIBUTION.md`), so this instance is under the
 * same licence as the text it holds. Declaring it here means `siprop=rightsinfo` reports it —
 * the same API path the agent used to read Fandom's own licence.
 */
$wgRightsUrl = 'https://creativecommons.org/licenses/by-sa/3.0/';
$wgRightsText = 'CC BY-SA 3.0 Unported';
$wgRightsIcon = '';

/**
 * A bot account may edit through the API, and nothing else may.
 *
 * Anonymous editing is off because this instance is reachable on the LAN while the dev server
 * runs, and an open wiki is an open wiki whatever its hostname.
 */
$wgGroupPermissions['*']['edit'] = false;
$wgGroupPermissions['*']['createaccount'] = false;
$wgGroupPermissions['bot']['edit'] = true;
$wgGroupPermissions['bot']['writeapi'] = true;

// Read access stays open: the agent reads far more than it writes, and the demo shows pages.
$wgGroupPermissions['*']['read'] = true;

/**
 * Keep the API's own rate limiting out of the way of seeding.
 *
 * Seeding posts 12 pages back to back, which trips the default `edit` limit for a fresh
 * account. This is our own instance with one client, so the limiter protects nothing here.
 */
$wgRateLimits['edit']['bot'] = [ 10000, 60 ];
$wgRateLimits['edit']['user'] = [ 10000, 60 ];

// Uploads stay off. The seed corpus is wikitext; images are referenced, never stored.
$wgEnableUploads = false;

// Surface errors in a local dev instance rather than a generic "internal error" page.
$wgShowExceptionDetails = true;
