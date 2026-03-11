var ps = ps || {};
ps.gameday = ps.gameday || {};
ps.gameday.resultPopup = ps.gameday.resultPopup || {};

ps.gameday.resultPopup.controller = (function($) {
    'use strict';

    var season;
    var event;
    var keepPopupOpen = false;

    /**
     * 
     * @param event event obj
     * @param season seasonEvent obj
     */
    var show = function(_event, _season, doneSendScore) {
        var updateResultPopupContentTemplate = $(".templates .update-result-popup-content-template").clone();

        season = _season;
        event = _event;
        updateResultPopupContentTemplate.find(".season-name").text(season.name);
        updateResultPopupContentTemplate.find(".date-info").text(event.date);

        if (event.inProgress) {
            updateResultPopupContentTemplate.find("input[name='options-inprogress'][value='yes']").prop("checked", true);
        } else {
            updateResultPopupContentTemplate.find("input[name='options-inprogress'][value='no']").prop("checked", true);
        }

        if (event.postponed) {
            updateResultPopupContentTemplate.find("input[name='options-postponed'][value='yes']").prop("checked", true);
        } else {
            updateResultPopupContentTemplate.find("input[name='options-postponed'][value='no']").prop("checked", true);
        }

        if (event.cancelled) {
            updateResultPopupContentTemplate.find("input[name='options-cancelled'][value='yes']").prop("checked", true);
        } else {
            updateResultPopupContentTemplate.find("input[name='options-cancelled'][value='no']").prop("checked", true);
        }

        updateResultPopupContentTemplate.find(".status-text input").val(event.status);
        updateResultPopupContentTemplate.find(".team_away").html(event.awayTeam);
        updateResultPopupContentTemplate.find(".team_home").html(event.homeTeam);

        updateResultPopupContentTemplate.find("#team_away").val(event.awayResult);
        updateResultPopupContentTemplate.find("#team_home").val(event.homeResult);

        updateResultPopupContentTemplate.data("eventId", event.id);
        updateResultPopupContentTemplate.data("seasonId", season.id);

        keepPopupOpen = false;
        updateResultPopupContentTemplate.find(".keep-popup-open").click(keepPopupOpenClick);

        ps.bootstrapExtensions.modalBuilder.build({
            title : "Update Result",
            size : ps.bootstrapExtensions.modalBuilder.size.small,
            closeButtonInHeader : true,
            content : updateResultPopupContentTemplate,
            buttons : [{
                text : "Cancel",
                type : "button",
                className : "btn-default btn-cancel",
                close : true
            }, {
                text : "Update",
                type : "button",
                className : "btn-primary btn-update",
                click : function(contentBody) {
                    var content = contentBody.find(".update-result-popup-content-template");
                    var data = {};
                    data.seasonId = content.data("seasonId");
                    var season = _season;
                    var event = _event;
                    event.inProgress = contentBody.find("input[name='options-inprogress'][value='yes']").is(":checked");
                    event.cancelled = contentBody.find("input[name='options-cancelled'][value='yes']").is(":checked");
                    event.postponed =  contentBody.find("input[name='options-postponed'][value='yes']").is(":checked");
                    event.status = $.trim(content.find(".status-text input").val());
                    event.awayResult = content.find("#team_away").val();
                    event.homeResult = content.find("#team_home").val();

                    _event = event;
                    sendScore(data, season, event, doneSendScore);
                }
            }]
        });
        ps.bootstrapExtensions.modalBuilder.show();
    };

    /**
     * Push score to server.
     * @param data data to send to server {seasonId, gamedayEvent}
     * @param season season data from cache
     * @param event event data from cache
     */
    var sendScore = function(data, season, event, doneSendScore) {
        if (!keepPopupOpen) {
            ps.bootstrapExtensions.modalBuilder.hide();
        }
        ps.bootstrapExtensions.loadingModal.show();
        data.gamedayEvent = JSON.stringify(event);
        $.ajax({
            url: "/admin/team/gameday/setScore.jsp",
            method: "POST",
            data: data
        }).done(doneSendScore(season, event)).always(function() {
            ps.bootstrapExtensions.loadingModal.hide();
        });
    };

    var keepPopupOpenClick = function() {
        if ($(this).is(":checked")) {
            keepPopupOpen = true;
            ps.bootstrapExtensions.modalBuilder.preventClose();
        } else {
            keepPopupOpen = false;
            ps.bootstrapExtensions.modalBuilder.enableClose();
        }
    };

    return {
        show : show
    }
})(jQuery);