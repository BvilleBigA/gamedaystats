/**
 * Created by villo on 1/5/16.
 */

var ps = ps || {};
ps.gameday = ps.gameday || {};

ps.gameday.utils = (function($) {
	'use strict';

	/**
	 * Used to hide offcanvas buttons (right panel hidden in tablet/mobile view)
	 */
	function hideFilters() {
		if ($(window).width() < 950) {
			$(".filters-container").removeClass("active");
		}
	}

	return {
		hideFilters:hideFilters
	}

})(jQuery);