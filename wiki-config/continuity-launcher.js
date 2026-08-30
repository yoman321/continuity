/* Continuity's launcher — installed onto the seeded wiki as `MediaWiki:Common.js`.
 *
 * `$wgUseSiteJs` defaults true (`wiki/includes/MainConfigSchema.php`), so this runs for every
 * reader of our own instance, anonymous ones included. It is the whole wiki-side integration:
 * a floating button in the bottom-right corner that opens the run view in a popup.
 *
 * **A corner button rather than a tab, on purpose.** It stands in for the browser extension a
 * real deployment would ship (`summary.md` §10) — the affordance a reader recognises as
 * "something else is watching this page", owing nothing to the skin's chrome and surviving a
 * skin change.
 *
 * **It does not render the gate here, and that is the invariant.** The popup is served from
 * Continuity's own origin, so `/api/state` and the draft routes stay same-origin — the
 * app keeps the "one origin, no CORS, no second deploy" property `backend/app.py` is built on
 * (`AGENTS.md` §2), and `FE/styles.css` never meets a skin's stylesheet. Everything injected
 * here is one button and one prefixed rule set.
 *
 * The origin is substituted at install time by `scripts/install_launcher.sh` from
 * `CONTINUITY_ORIGIN`. It is not committed: a deploy URL is a deployment identifier, and those
 * are named only in `.env` (`AGENTS.md` §2).
 *
 * The same URL contract works from a bookmarklet on a wiki we do *not* control, which is the
 * only reason a browser extension was not needed:
 *
 *   javascript:(function(){window.open('ORIGIN/#/verify?page='+
 *     encodeURIComponent(location.pathname.split('/wiki/')[1]||''),'continuity-verify',
 *     'width=960,height=980');})()
 */
( function () {
	'use strict';

	var ORIGIN = '__CONTINUITY_ORIGIN__';

	mw.loader.using( [ 'mediawiki.util' ] ).then( function () {
		// Articles only. The run has nothing to say about Talk:, MediaWiki: or Special:.
		if ( mw.config.get( 'wgNamespaceNumber' ) !== 0 ) {
			return;
		}

		// `wgCurRevisionId` is the revision the reader is looking at. The gate carries it so a
		// draft can be shown against the revision it was taken from once the ledger is stored
		// (`AGENTS.md` §2, the single-editor assumption).
		var url = ORIGIN + '/#/verify?page=' +
			encodeURIComponent( mw.config.get( 'wgPageName' ) ) +
			'&rev=' + encodeURIComponent( mw.config.get( 'wgCurRevisionId' ) );

		// Every selector is prefixed: this runs inside a skin we do not own, so no rule here
		// may match anything but our own button.
		mw.util.addCSS(
			'.continuity-launch{position:fixed;right:22px;bottom:22px;z-index:900;' +
			'display:flex;align-items:center;gap:9px;padding:9px 15px 9px 10px;' +
			'border:1px solid #12514e;border-radius:999px;background:#17605c;color:#fff;' +
			'font:600 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;' +
			'cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.16),0 10px 26px rgba(0,0,0,.18);' +
			'transition:transform .14s ease,box-shadow .14s ease}' +
			'.continuity-launch:hover{transform:translateY(-2px);' +
			'box-shadow:0 4px 10px rgba(0,0,0,.18),0 14px 34px rgba(0,0,0,.22)}' +
			'.continuity-launch:focus-visible{outline:2px solid #fff;outline-offset:2px}' +
			'.continuity-launch-mark{display:flex;align-items:center;justify-content:center;' +
			'width:22px;height:22px;border-radius:6px;background:#fff;color:#17605c;' +
			'font-weight:700;font-size:13px}' +
			'@media(max-width:640px){.continuity-launch-label{display:none}' +
			'.continuity-launch{padding:10px}}'
		);

		var button = document.createElement( 'button' );
		button.type = 'button';
		button.className = 'continuity-launch';
		button.title = 'Review what Continuity has drafted for this page';
		button.innerHTML =
			'<span class="continuity-launch-mark">C</span>' +
			'<span class="continuity-launch-label">Continuity</span>';

		button.addEventListener( 'click', function () {
			// No `noopener`: the gate calls `window.opener.location.reload()` once a publish
			// succeeds, so the page behind it repaints with the edit applied. That
			// back-reference is load-bearing, not an oversight.
			window.open( url, 'continuity-verify',
				'popup=yes,width=960,height=980,scrollbars=yes,resizable=yes' );
		} );

		document.body.appendChild( button );
	} );
}() );
