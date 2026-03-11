/**
 * Created by villo on 6/4/16.
 *
 * This extension create a modal popup with a loading progress bar.
 *
 * Usage:
 *  For showing: ps.bootstrapExtensions.loadingModal.show();
 *  For hiding: ps.bootstrapExtensions.loadingModal.hide();
 *
 *  Also you can customize the message:
 *  ps.bootstrapExtensions.loadingModal.show("Please wait...");
 *  
 *  You can also specify a custom class for the modal:
 *  ps.bootstrapExtensions.loadingModal.show("Please wait...", {customStyleClass: "gameday"});
 *  
 */
var ps = ps || {};
ps.bootstrapExtensions = ps.bootstrapExtensions || {};
ps.bootstrapExtensions.loadingModal = (function ($) {
    'use strict';

    // Creating modal dialog's DOM
    var $dialog = $(
        '<div class="modal fade fade-loading" data-backdrop="static" data-keyboard="false" tabindex="-1" role="dialog" aria-hidden="true" style="padding-top:15%; overflow-y:visible;">' +
        '<div class="modal-dialog modal-dialog-loading modal-m">' +
        '<div class="modal-content">' +
        '<div class="modal-header"><h3 style="margin:0;"></h3></div>' +
        '<div class="modal-body">' +
        '<div class="progress progress-striped active" style="margin-bottom:0;"><div class="progress-bar" style="width: 100%"></div></div>' +
        '</div>' +
        '</div></div></div>');

    return {
        /**
         * Opens our dialog
         * @param message Custom message
         * @param options Custom options:
         * 				  options.dialogSize - bootstrap postfix for dialog size, e.g. "xs", "sm", "m";
         * 				  options.progressType - bootstrap postfix for progress bar type, e.g. "success", "warning".
         */
        show: function (message, options) {
            // Assigning defaults
            if (typeof options === 'undefined') {
                options = {};
            }
            if (typeof message === 'undefined') {
                message = 'Loading';
            }
            var settings = $.extend({
                dialogSize: 'xs',
                progressType: '',
                onHide: null // This callback runs after the dialog was hidden
            }, options);

            // Configuring dialog
            $dialog.find('.modal-dialog').attr('class', 'modal-dialog').addClass('modal-' + settings.dialogSize);
            $dialog.find('.progress-bar').attr('class', 'progress-bar');
            if (settings.progressType) {
                $dialog.find('.progress-bar').addClass('progress-bar-' + settings.progressType);
            }
            $dialog.find('h3').text(message);
            // Adding callbacks
            if (typeof settings.onHide === 'function') {
                $dialog.off('hidden.bs.modal').on('hidden.bs.modal', function (e) {
                    settings.onHide.call($dialog);
                });
            }
            // Opening dialog
            $dialog.modal();
            $(".modal-backdrop:last").addClass("modal-backdrop-loading");
            // specify custom style class
            if (settings.customStyleClass) {
            	$dialog.addClass(settings.customStyleClass);
            	$dialog.prev().addClass(settings.customStyleClass);
            }
        },
        /**
         * Closes dialog
         */
        hide: function () {
            $dialog.modal('hide');
        }
    };

})(jQuery);