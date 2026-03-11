var ps = ps || {};
ps.gameday = ps.gameday || {};
ps.gameday.scorePopup = ps.gameday.scorePopup || {};

ps.gameday.scorePopup.controller = (function ($) {
    'use strict';

    var STATUS_NOT_STARTED = -2;
    var STATUS_IN_PROGRESS = -1;

    var STATCREW_FOOTBALL = 0;
    var STATCREW_BASEBALL = 1;
    var STATCREW_BASKETBALL = 2;
    var STATCREW_VOLLEYBALL = 4;
    var STATCREW_SOFTBALL = 11;

    var season;
    var event;
    var keepPopupOpen = false;

    /**
     *
     * @param event event obj
     * @param season seasonEvent obj
     */
    var show = function (_event, _season, doneSendScore) {
        var scorePopupContentTemplate = $(".templates .score-popup-content-template").clone();

        season = _season;
        event = _event;
        scorePopupContentTemplate.find(".season-name").text(season.name);
        scorePopupContentTemplate.find(".date-info").text(event.date);

        scorePopupContentTemplate.find(".team_1").text(event.awayTeam);
        scorePopupContentTemplate.find(".team_2").text(event.homeTeam);
        scorePopupContentTemplate.find(".status-text input").val(event.status);
        var status = scorePopupContentTemplate.find("#status");
        $(season.statusOptions).each(function (index, value) {
            if(season.prefs['pioneer_ko'] || index <= 50) {
                $("<option value='" + index + "'>" + value + "</option>").appendTo(status);
            }
        });
        keepPopupOpen = false;
        scorePopupContentTemplate.find(".keep-popup-open").click(keepPopupOpenClick);

        scorePopupContentTemplate.data("eventId", event.id);
        scorePopupContentTemplate.data("seasonId", season.id);

        var modalSize = ps.bootstrapExtensions.modalBuilder.size.small;
        if (event.hasScorebug) {
            modalSize = ps.bootstrapExtensions.modalBuilder.size.normal;
            scorePopupContentTemplate.find(".general-container").removeClass("col-sm-12").addClass("col-sm-6");
            scorePopupContentTemplate.find(".scorebug-sport-specific").removeClass("col-sm-12").addClass("col-sm-6");
        }

        ps.bootstrapExtensions.modalBuilder.build({
            title: "Update Score",
            size: modalSize,
            closeButtonInHeader: true,
            content: scorePopupContentTemplate,
            buttons: [{
                text: "Cancel",
                type: "button",
                className: "btn-default btn-cancel",
                close: true
            }, {
                text: "Update",
                type: "submit",
                className: "btn-primary btn-update"
            }],
            submit: function (e) {
                if (e.isDefaultPrevented()) {
                    return false;
                }
                var content = $(e.target).parent();

                var data = {};
                data.seasonId = content.data("seasonId");
                event.id = content.data("eventId");
                event.statusCode = parseInt(content.find("#status").val(), 10);
                event.status = $.trim(content.find(".status-text input").val());
                event.inProgress = event.statusCode == STATUS_IN_PROGRESS;
                event.awayResult = content.find("#team_1").val();
                event.homeResult = content.find("#team_2").val();
                prepareToSendScorebug(event, season, content);

                sendScore(data, season, event, doneSendScore);
                return false;
            },
            validationOptions: {
                custom: {
                    requiredStartedGame: function ($el) {
                        var form = $($el).parents("form");
                        var status = form.find("#status");
                        if (parseInt(status.val(), 10) >= STATUS_IN_PROGRESS) {
                            if ($.trim($el.val()) == "" || !$.isNumeric($el.val())) {
                                return false;
                            }
                            return true;
                        } else {
                            return true;
                        }
                    },
                    requiredTiebreakGame: function ($el) {
                        var form = $($el).parents("form");
                        const statusCode = parseInt(form.find("#status").val(), 10);
                        const awayResult = form.find("#team_1").val();
                        const homeResult = form.find("#team_2").val();
                        if (season.prefs['pioneer_ko'] && statusCode > 50 && awayResult === homeResult) {
                            return false;
                        }
                        return true;
                    }
                },
                errors: {
                    requiredStartedGame: "Please fill out this field with numbers",
                    requiredTiebreakGame: "Please change the score to break the tie"
                }
            }
        });

        scorePopupContentTemplate.find("#status").change(toggleStatus);

        scorePopupContentTemplate.find("#team_1").val(event.awayResult);
        scorePopupContentTemplate.find("#team_2").val(event.homeResult);
        scorePopupContentTemplate.find("#status").val(event.statusCode).change();
        scorePopupContentTemplate.find(".status-text input").val(event.status);
        if (event.hasScorebug) {
            prepareToShowScorebug(_event, _season, scorePopupContentTemplate);
        }
        //
        ps.bootstrapExtensions.modalBuilder.show();

    };

    /**
     * Show or hide status textbox if the game it's in progress (in score popups)
     */
    var toggleStatus = function () {
        var containerStatusText = $(this).parents(".form-group").find(".status-text");
        var scoreContainers = $(this).parents("form").find(".score-container");
        var scorebugSportSpecificContainer = $(this).parents("form").find(".scorebug-sport-specific");

        if ($(this).val() == STATUS_IN_PROGRESS.toString() || $(this).val() == "yes") {
            containerStatusText.fadeIn("fast");
        } else {
            containerStatusText.fadeOut("fast");

        }
        if ($(this).val() == STATUS_NOT_STARTED.toString()) {
            scoreContainers.fadeOut("fast");
            scoreContainers.find("input").val("");
            scorebugSportSpecificContainer.fadeOut("fast");
            scorebugSportSpecificContainer.find("input").val("");


        } else {
            scoreContainers.fadeIn("fast");
            scorebugSportSpecificContainer.fadeIn("fast");
        }
        var form = $(this).parents("form");
        if (form.length > 0) {
            form.validator('validate');
            form.find("input").change().focusout();
        }
    };

    /**
     * Push score to server.
     * @param data data to send to server {seasonId, gamedayEvent}
     * @param season season data from cache
     * @param event event data from cache
     */
    var sendScore = function (data, season, event, doneSendScore) {
        if (!keepPopupOpen) {
            ps.bootstrapExtensions.modalBuilder.hide();
        }
        ps.bootstrapExtensions.loadingModal.show();
        data.gamedayEvent = JSON.stringify(event);
        $.ajax({
            url: "/admin/team/gameday/setScore.jsp",
            method: "POST",
            data: data
        }).done(doneSendScore(season, event)).always(function () {
            ps.bootstrapExtensions.loadingModal.hide();
        });
    };

    var keepPopupOpenClick = function () {
        if ($(this).is(":checked")) {
            keepPopupOpen = true;
            ps.bootstrapExtensions.modalBuilder.preventClose();
        } else {
            keepPopupOpen = false;
            ps.bootstrapExtensions.modalBuilder.enableClose();
        }
    };

    var prepareToShowScorebug = function (_event, _season, _template) {
        if (_event.statusCode > STATUS_NOT_STARTED) {
            _template.find(".scorebug-sport-specific").show();
        }
        switch (_season.statcrewSportId) {
            case STATCREW_FOOTBALL:
                var scorebugContent = _template.find(".scorebug-football-additional");
                scorebugContent.show();
                if (_event.scorebugJsonData) {
                    scorebugContent.find("#football_down").val(event.scorebugJsonData.down);
                    scorebugContent.find("#football_togo").val(event.scorebugJsonData.toGo);
                    scorebugContent.find("#football_tol_team_1").val(event.scorebugJsonData.visitorTimeoutsLeft);
                    scorebugContent.find("#football_tol_team_2").val(event.scorebugJsonData.homeTimeoutsLeft);
                    scorebugContent.find("input[name='period']").val(event.scorebugJsonData.currentPeriod);
                }
                break;
            case STATCREW_BASEBALL:
            case STATCREW_SOFTBALL:
                var scorebugContent = _template.find(".scorebug-baseball-additional");
                scorebugContent.show();
                if (_event.scorebugJsonData) {
                    if (event.scorebugJsonData.periodName !== undefined) {
                        scorebugContent.find("#baseball_period_name").val(event.scorebugJsonData.periodName);
                    }
                    scorebugContent.find("input[name='period']").val(event.scorebugJsonData.currentPeriod);
                    $(event.scorebugJsonData.runners).each(function(index) {
                        scorebugContent.find(".runners-container input[type='checkbox']:eq(" + index + ")").prop("checked", this);
                    });
                    scorebugContent.find("#baseball_outs").val(event.scorebugJsonData.outs);
                }
                break;
            case STATCREW_BASKETBALL:
                var scorebugContent = _template.find(".scorebug-basketball-additional");
                scorebugContent.show();
                scorebugContent.find(".visitor-team").text(event.awayTeam);
                scorebugContent.find(".home-team").text(event.homeTeam);
                if (_event.scorebugJsonData) {
                    scorebugContent.find("input[name='period']").val(event.scorebugJsonData.currentPeriod);
                    scorebugContent.find("#basketball_fouls_team_1").val(event.scorebugJsonData.visitorFouls);
                    scorebugContent.find("#basketball_fouls_team_2").val(event.scorebugJsonData.homeFouls);
                    scorebugContent.find("#basketball_timeouts_team_1").val(event.scorebugJsonData.visitorTimeoutsUsed);
                    scorebugContent.find("#basketball_timeouts_team_2").val(event.scorebugJsonData.homeTimeoutsUsed);
                }
                break;
            case STATCREW_VOLLEYBALL:
                var scorebugContent = _template.find(".scorebug-volleyball-additional");
                scorebugContent.show();
                scorebugContent.find(".points-visitor-container .visitor-team").text(event.awayTeam);
                scorebugContent.find(".points-home-container .home-team").text(event.homeTeam);
                if (_event.scorebugJsonData) {
                    scorebugContent.find("#volley_team_1").val(event.scorebugJsonData.visitorCurrentPoints);
                    scorebugContent.find("#volley_team_2").val(event.scorebugJsonData.homeCurrentPoints);
                }
                break;
            default:
                var scorebugContent = _template.find(".scorebug-other-additional");
                scorebugContent.show();
                if (_event.scorebugJsonData) {
                    scorebugContent.find("input[name='period']").val(event.scorebugJsonData.currentPeriod);
                }
                break;
        }
    };

    var prepareToSendScorebug = function (_event, _season, _content) {
        if (!_event.scorebugJsonData) {
            _event.scorebugJsonData = {};
        }
        switch (_season.statcrewSportId) {
            case STATCREW_FOOTBALL:
                var scorebugContent = _content.find(".scorebug-football-additional");
                _event.scorebugJsonData.down = scorebugContent.find("#football_down").val();
                _event.scorebugJsonData.toGo = scorebugContent.find("#football_togo").val();
                _event.scorebugJsonData.visitorTimeoutsLeft = scorebugContent.find("#football_tol_team_1").val();
                _event.scorebugJsonData.homeTimeoutsLeft = scorebugContent.find("#football_tol_team_2").val();
                _event.scorebugJsonData.currentPeriod = scorebugContent.find("input[name='period']").val();
                break;
            case STATCREW_BASEBALL:
            case STATCREW_SOFTBALL:
                var scorebugContent = _content.find(".scorebug-baseball-additional");
                _event.scorebugJsonData.outs = scorebugContent.find("#baseball_outs").val();
                var runners = [];
                scorebugContent.find(".runners-container input[type='checkbox']").each(function(index) {
                    runners[index] = $(this).is(":checked");
                });
                _event.scorebugJsonData.runners = runners;
                _event.scorebugJsonData.periodName = scorebugContent.find("#baseball_period_name").val();
                _event.scorebugJsonData.currentPeriod = scorebugContent.find("input[name='period']").val();
                break;
            case STATCREW_BASKETBALL:
                var scorebugContent = _content.find(".scorebug-basketball-additional");
                _event.scorebugJsonData.currentPeriod = scorebugContent.find("input[name='period']").val();
                _event.scorebugJsonData.visitorFouls = scorebugContent.find("#basketball_fouls_team_1").val();
                _event.scorebugJsonData.homeFouls = scorebugContent.find("#basketball_fouls_team_2").val();
                _event.scorebugJsonData.visitorTimeoutsUsed = scorebugContent.find("#basketball_timeouts_team_1").val();
                _event.scorebugJsonData.homeTimeoutsUsed = scorebugContent.find("#basketball_timeouts_team_2").val();
                break;
            case STATCREW_VOLLEYBALL:
                var scorebugContent = _content.find(".scorebug-volleyball-additional");
                _event.scorebugJsonData.visitorCurrentPoints = scorebugContent.find("#volley_team_1").val();
                _event.scorebugJsonData.homeCurrentPoints = scorebugContent.find("#volley_team_2").val();
                break;
            default:
                var scorebugContent = _content.find(".scorebug-other-additional");
                _event.scorebugJsonData.currentPeriod = scorebugContent.find("input[name='period']").val();
                break;
        }
    };

    return {
        show: show
    }
})(jQuery);