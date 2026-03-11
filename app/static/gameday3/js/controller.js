var ps = ps || {};
ps.gameday = ps.gameday || {};

ps.gameday.controller = (function($) {
    'use strict';
    
    var STATUS_FINAL = 0;
    var todayDate = null;
    var selectedDate = null;
    var selectedSport = null;
    var selectedDateString = function() {
        return ps.gameday.controller.selectedDate.format("L");
    };
    var showsHiddenSeasons = false;
    var cachedData = [];

	/**
	 * Build all date elements
	 * @param today MomentJS object
	 */
	var buildDates = function buildDates(today) {
        $(".dates").empty();
		var container = $(".row.dates");
		var dateTemplate = $(".templates .date-template");
		container.append(buildDateItem(dateTemplate, today, true));

        dateTemplate.find(".loading-number-events").hide();
		var dayBefore = moment(today);
		var dayAfter = moment(today);
		for (var i = 1; i < 4; i++) {
			dayBefore.subtract(1, "days");
			dayAfter.add(1, "days");
			container.prepend(buildDateItem(dateTemplate, dayBefore, false,
					i >= 2, i === 3));
			container.append(buildDateItem(dateTemplate, dayAfter, false,
					i >= 2, i === 3));
            // doCacheForDay(dayBefore);
            // doCacheForDay(dayAfter);
		}
	};

	/**
	 * Build date item to append to DOM.
	 * @param template jQuery object template DOM
	 * @param date MomentJS Object for specific date
	 * @param isSelected boolean for selected value
	 * @returns {jQuery} element with date to append to DOM
	 */
	var buildDateItem = function(template, date, isSelected, hiddenXs, hiddenMd) {
		var todayElement = template.clone();
		todayElement.removeClass("date-template");
		if (isSelected) {
			todayElement.find(".thumbnail").addClass("selected");
		} else {
			todayElement.find("a").click(function() {
				$(".datepicker").data("DateTimePicker").date($(this).parent().data("date"));
                ps.gameday.utils.hideFilters();
			});
		}
		if (hiddenXs) {
			todayElement.addClass("hidden-xxs");
		}
		if (hiddenMd) {
			todayElement.addClass("hidden-xs hidden-sm hidden-md");
		}
        var currentDateString = date.format("MM/DD/YYYY");
		todayElement.attr("data-date", currentDateString);
        if (date.isSame(ps.gameday.controller.todayDate, "day")) {
            todayElement.find(".top-legend").text("TODAY");
        } else {
            todayElement.find(".top-legend").text(date.format("ddd"));
        }
		todayElement.find(".date").text(date.format("M/D"));
		return todayElement;
	};

    var buildSeasonsList = function(seasonsData) {
        if (!cachedData[selectedDateString()] || !cachedData[selectedDateString()].allSeasons) {
            cachedData[selectedDateString()].allSeasons = seasonsData;
        }
        $(".go-directly-list > a:not(.no-erasable)").remove();
        $(seasonsData).each(function(index, value) {
            // Populate right seasons list.
            $('<a href="/admin/team/season/season.jsp?season_id=' + value.id + '" class="list-group-item">'
                + value.name + '</a>').appendTo(".go-directly-list");
        });
        $(".loading-seasons-links").hide();
    }

    /**
     * Build all seasons layout
     * @param seasonsData seasons from ajax call.
     */
	var buildSeasons = function(seasonsData) {
		var seasonTemplate = $(".templates .season-container-template");
        var dateItem = $(".dates .date-item[data-date='" + selectedDateString() + "']");
        dateItem.find(".number").text("0");
        var totalEvents = 0;
		$(seasonsData).each(function(index, value) {
            totalEvents += value.eventsCount;

            if (cachedData[selectedDateString()][index] === undefined) {
                value.fetched = moment();
                cachedData[selectedDateString()][index] = value;
            }
            value.index = index;
			var item = buildSeasonItem(seasonTemplate, value);
			$(".all-rows").append(item);

            var cached = cachedData[selectedDateString()][value.index];
            if (cached.events !== undefined) {
                populateEvents(value.id, cached);
                expandSeasonContainer(item);
            }
		});
        $(".all-rows").prepend(`<h2 style="text-align: center">${totalEvents} Events today</h2><br/>`);

        ps.bootstrapExtensions.loadingModal.hide();
        initTooltips();
	};

    /**
     * Build a season layout
     * @param template seasonItem template
     * @param seasonInfo season data from ajax call
     * @returns {jQuery} seasonItem ready to append to DOM
     */
    var buildSeasonItem = function(template, seasonInfo) {
        var item = template.clone();
        if (seasonInfo.hidden) {
            $(".show-hide-seasons-container").show();
        	toggleSeasonHideTooltip(item.find(".btn-hide-season"), false);
            item.addClass("hidden-season");
            item.find(".glyphicon-eye-open").removeClass("glyphicon-eye-open").addClass("glyphicon-eye-close");
        } else {
            item.find(".content-container:not(.collapsed)").show();
            item.fadeIn("fast");
        }
        item.find(".title-container a.right-button").show();
        item.find(".btn-hide-season").click(toggleSeasonHide);
        item.data("index", seasonInfo.index);
        item.remove("season-container-template");
        item.find(".title b.season-name").html(seasonInfo.name);
        item.find(".season-events-number").html(" (" + seasonInfo.eventsCount + ")");
        var manageSeason = item.find(".manage-season");
        manageSeason.attr("href", manageSeason.attr("href") + seasonInfo.id);
        item.attr("data-id", seasonInfo.id);
        item.attr("data-index", seasonInfo.index);
        if (seasonInfo.statcrewSportId !== undefined) {
            item.attr("data-statcrewSportId", seasonInfo.statcrewSportId);
        }
        switch (seasonInfo.seasonSportSharingId) {
            case 0:
                item.addClass("h2h h2h-no-meet");
                break;
            case 3:
                item.addClass("h2h h2h-meet");
                break;
            default:
                item.addClass("individual-sport");
                break;
        }
        return item;
    };

    /**
     * Entry point to populate seasons from scratch.
     */
	var populateSeasons = function() {
        $(".all-rows").empty();
        $(".no-events-container").hide();
        $(".show-hide-seasons-container").hide();
        ps.bootstrapExtensions.loadingModal.show("Loading", {customStyleClass: "gameday"});
        if (!isDayCached(selectedDateString())) {
            cachedData[selectedDateString()] = [];
            $.ajax({
                url: "/admin/team/gameday/seasonListByDate.json",
                data: {
                    date: selectedDateString()
                },
                dataType: "json"
            }).done(function (data, textStatus, jqXHR) {
            	if (data.length == 0) {
                	displayNoData(selectedDateString());
                } else {
                	buildSeasons(data);
                }
            }).fail(function (jqXHR, textStatus, errorThrown) {
                ps.bootstrapExtensions.modalBuilder.build({
                    title : "Error",
                    type : ps.bootstrapExtensions.modalBuilder.type.error,
                    size : ps.bootstrapExtensions.modalBuilder.size.normal,
                    closeButtonInHeader : true,
                    content : "Oops! Something went wrong with your seasons<br/><br/>Try again in a while.",
                    buttons : [{
                        text : "Ok",
                        type : "btn-primary",
                        className : "btn-cancel",
                        close : true
                    }]
                });
                ps.bootstrapExtensions.modalBuilder.show();
                ps.bootstrapExtensions.loadingModal.hide();
            }).always(function () {
                addClickEventsToSeason();
            });

            $(".loading-seasons-links").show();
            $(".go-directly-list > a:not(.no-erasable)").remove();
            $.ajax({
                url: "/admin/team/gameday/seasonListByDate.json",
                data: {
                    date: selectedDateString(),
                    allSeasons: true
                },
                dataType: "json"
            }).done(function (data, textStatus, jqXHR) {
                buildSeasonsList(data);
            }).fail(function (jqXHR, textStatus, errorThrown) {
                ps.bootstrapExtensions.modalBuilder.build({
                    title : "Error",
                    type : ps.bootstrapExtensions.modalBuilder.type.error,
                    size : ps.bootstrapExtensions.modalBuilder.size.normal,
                    closeButtonInHeader : true,
                    content : "Oops! Something went wrong with your seasons<br/><br/>Try again in a while.",
                    buttons : [{
                        text : "Ok",
                        type : "btn-primary",
                        className : "btn-cancel",
                        close : true
                    }]
                });
                ps.bootstrapExtensions.modalBuilder.show();
                $(".loading-seasons-links").hide();
            });
        } else {
            buildSeasons(cachedData[selectedDateString()]);
            buildSeasonsList(cachedData[selectedDateString()].allSeasons);
            addClickEventsToSeason();
        }
	};

    /**
     * Entry point to populate events when a season is loaded.
     * @param seasonId Season ID
     * @param cached Season cached object
     * @param seasonQuantity Total quantity of seasons
     */
    var populateEvents = function(seasonId, cached) {
        var seasonContainer = $('.all-rows .season-container[data-id="'
            + seasonId + '"]');

        // If it's not cached, get data from server
        if (cached.events === undefined) {
            seasonContainer.find(".loading-number-events").show();
            $.ajax({
                url : "/admin/team/gameday/seasonEvents.json",
                data : {
                    seasonId : seasonId,
                    date : selectedDateString()
                },
                dataType : "json"
            }).done(doneEventFunction(seasonContainer, cached))
                .fail(failEventFunction(seasonContainer));
        } else { // If it's cached, use cache.
            buildEvents(cached.events, seasonContainer);
        }
    };

    /**
     * Done event function from ajax call.
     * @param seasonContainer Season container jQuery object
     * @param cached Season cached object
     * @param seasonQuantity Total quantity of seasons
     * @returns {Function} Done function for use in $.ajax
     */
    var doneEventFunction = function(seasonContainer, cached) {
        return function(events, textStatus, jqXHR) {
            cached.events = events;
            buildEvents(events, seasonContainer);
            seasonContainer.find(".loading-number-events").hide();
        }
    };

    /**
     * Fail event function from ajax call.
     * @param seasonContainer Season container jQuery object
     * @param seasonQuantity Season cached object
     * @returns {Function} Fail function for use in $.ajax
     */
    var failEventFunction = function(seasonContainer) {
        return function(jqXHR, textStatus, errorThrown) {
            seasonContainer.show();
            seasonContainer.addClass("rendered");
            seasonContainer.find(".title-container").addClass("alert-danger");
            seasonContainer.find(".error-icon").removeClass("hide").addClass(
                "glyphicon-exclamation-sign").attr("title",
                "A problem ocurred while loading data from this season.")
                .tooltip({
                    container : "body",
                    delay : {
                        "show" : 500,
                        "hide" : 100
                    }
                });
            seasonContainer.find(".loading-number-events").hide();
        }
    };

    /**
     * Build all events for a season. Also updates events in date.
     * @param eventData events from ajax call
     * @param seasonContainer Season container jQuery object
     * @param seasonQuantity Total quantity of seasons
     */
	var buildEvents = function(eventData, seasonContainer) {
        if (!seasonContainer.hasClass("rendered")) {
            var dateItem = $(".dates .date-item[data-date='" + selectedDateString() + "']");
            updateNumberEventsForDate(eventData, dateItem);

            var shouldVisible = true;
            if (seasonContainer.hasClass("hidden-season")) {
                shouldVisible = showsHiddenSeasons;
            } else if (ps.gameday.controller.selectedSport != null && ps.gameday.controller.selectedSport != seasonContainer.attr("data-statcrewSportId")) {
                shouldVisible = false;
            }

            if (shouldVisible) {
                seasonContainer.fadeIn("fast");
            }
            var eventTemplate = $(".templates .event-template");
            $(eventData).each(function (index, value) {
                var additionalInfo = {};
                additionalInfo.seasonId = $(seasonContainer).data("id");
                additionalInfo.isH2H = seasonContainer.hasClass("h2h");
                additionalInfo.statcrewSportId = seasonContainer.attr("data-statcrewSportId");
                additionalInfo.index = index;
                var item = buildEventItem(eventTemplate, value, additionalInfo);
                buildEventLegends(value, item);
                seasonContainer.find(".events").append(item);
            });
            buildSeasonLegends(seasonContainer);
            seasonContainer.find(".content-container:not(.collapsed)").show();
            seasonContainer.find(".title-container a.right-button").show();
            seasonContainer.addClass("rendered");
        }
	};

    /**
     * Build an event item
     * @param template eventItem template
     * @param eventInfo event data from ajax call.
     * @param additionalInfo needed info to render (seasonId, isH2H,
     * statcrewSportId, index)
     * @returns {jQuery} eventItem ready to append to DOM
     */
	var buildEventItem = function(template, eventInfo, additionalInfo) {
		var item = template.clone();
		item.attr("data-id", eventInfo.id);
        item.data("index", additionalInfo.index);
        item.removeClass("event-template");
        //
        if (additionalInfo.isH2H) {
            if (eventInfo.tba) {
                item.find(".title .text-view-event b").html(eventInfo.date.split(" ")[0] + " TBA");
            } else {
                item.find(".title .text-view-event b").html(eventInfo.date);
            }
            item.find(".head-2-head-sport-col .away-team-name").html(eventInfo.awayTeam);
            item.find(".head-2-head-sport-col .home-team-name").html(eventInfo.homeTeam);
        } else {
            item.find(".title .text-view-event b").html(eventInfo.date.split(" ")[0]);
            var teamName = checkNullAndFormatValue(eventInfo.awayTeam, " ");
            teamName += checkNullAndFormatValue(eventInfo.awayResult, " ");
            teamName += checkNullAndFormatValue(eventInfo.homeTeam, " : ");
            teamName += checkNullAndFormatValue(eventInfo.homeResult, " ");
            teamName += checkNullAndFormatValue(eventInfo.neutralSite, " @ ");
            item.find(".individual-sport-col .team-name").html(teamName);
        }
        updateMissingInfoIcon(selectedDateString());

        if (eventInfo.statusFormatted == "") {
            eventInfo.statusFormatted = "&nbsp;"
        }
        item.find(".status-event").html(eventInfo.statusFormatted);

        addClickEventsToEvent(item, eventInfo, additionalInfo);
		return item;
	};

    /***
     * Hide or display the missing info icon next to the specified date;
     * @param date. A moment date.
     */
	var updateMissingInfoIcon = function(stringDate){
        var infoIcon = $(".dates .date-item[data-date='" + stringDate + "'] .info-icon");
        infoIcon.hide();
	    $.each(cachedData[stringDate], function(seasonIndex, season){
	        $.each(season.events, function(eventIndex, event){
                if ((event.statusCode >= STATUS_FINAL || isManualScheduleEventSetToFinal(event)) && !hasResult(event)) {
                    var errorMessage = "You need to set scores for events with status 'Final'";
                    infoIcon.data("original-title", errorMessage)
                        .attr("title", errorMessage)
                        .tooltip('fixTitle')
                        .tooltip('setContent');
                    infoIcon.fadeIn("fast").css("display","inline-block");
                    return;
                }
            });
        });
    };

    /**
     * Build legends for an event
     * @param eventInfo event data from ajax call.
     * @param eventContainer Event container jQuery object
     * @param seasonContainer Season container jQuery object
     */
    var buildEventLegends = function(eventInfo, eventContainer) {
        var flags = eventContainer.find(".legends");
        eventContainer.toggleClass("in-progress", eventInfo.inProgress);
        flags.find(".cancelled").toggleClass("visible", eventInfo.cancelled);
        flags.find(".postponed").toggleClass("visible", eventInfo.postponed);
        flags.find(".conference").toggleClass("visible", eventInfo.conference);
        flags.find(".regional").toggleClass("visible", eventInfo.regional);
        flags.find(".division").toggleClass("visible", eventInfo.division);
        flags.find(".overall").toggleClass("visible", !eventInfo.overall);
        flags.find(".primetime").toggleClass("visible", eventInfo.primetime);
        var missingInfo = isManualScheduleEventSetToFinal(eventInfo) && !hasResult(eventInfo);
        eventContainer.toggleClass("info-missing", missingInfo);
    };

    /**
     *
     * @param seasonId
     * @returns {season}
     */
    var getSeasonFromCache = function(seasonId){
        var season = null;
        $.each(cachedData[selectedDateString()], function(index, _season){
            if(_season.id === seasonId){
                season = _season;
                return;
            }
        });
        return season;
    };

    /**
     * Toggles legend summary for a season container based on the season events.
     * @param seasonContainer
     */
    var buildSeasonLegends = function(seasonContainer){
        var season =  getSeasonFromCache(seasonContainer.data('id'));
        var legends = seasonContainer.find(".content-container .legend-groups");
        if (season != null){
            legends.find("span").removeClass("visible");
            $(season.events).each(function(index, eventInfo) {
                if (eventInfo.inProgress) {
                    legends.find(".in-progress").addClass("visible");
                }
                if (eventInfo.cancelled) {
                    legends.find(".cancelled").addClass("visible");
                }
                if (eventInfo.postponed) {
                    legends.find(".postponed").addClass("visible");
                }
                if (eventInfo.conference) {
                    legends.find(".conference").addClass("visible");
                }
                if (eventInfo.regional) {
                    legends.find(".regional").addClass("visible");
                }
                if (eventInfo.division) {
                    legends.find(".division").addClass("visible");
                }
                if (!eventInfo.overall) {
                    legends.find(".overall").addClass("visible");
                }
                if (eventInfo.primetime) {
                    legends.find(".primetime").addClass("visible");
                }
                var missingInfo = isManualScheduleEventSetToFinal(eventInfo) && !hasResult(eventInfo);
                if (missingInfo) {
                    legends.find(".info-missing").addClass("visible");
                }
            });
            legends.find(".separator").removeClass("separator");
            //Timeout is required to wait for the separator class removal;
            setTimeout(function(){
                $.each(legends.find(".legend-group"), function(index, legendGroup){
                    $(legendGroup).find("span:visible:not(:last)").addClass("separator");
                });
            }, 100);
        }
    }

    /**
     * Adds click events for all seasons containers
     */
    var addClickEventsToSeason = function() {
        $(".season-container .title-container .title .right-button").click(toggleCollapse);
    };

    /**
     * Add click events for a event
     * @param scope (jQuery) eventItem
     * @param eventInfo data from ajax call
     * @param additionalInfo needed info to render (seasonId, isH2H,
     * statcrewSportId, index)
     */
    var addClickEventsToEvent = function(scope, eventInfo, additionalInfo) {
        $(scope).find(".btn-score").click(ps.gameday.controller.scoreClick);
        $(scope).find(".btn-results").click(ps.gameday.controller.updateResultClick);
        scope.find(".title .text-view-event").attr("href", scope.find(".title" +
                " .text-view-event").attr("href") + eventInfo.id);
        scope.find(".title .btn-edit-event").attr("href", scope.find(".title" +
                " .btn-edit-event").attr("href") + eventInfo.id);
        if (additionalInfo.isH2H) {
            var twitterUrl = scope.find(".btn-tweet").attr("href");
            twitterUrl = twitterUrl.replace("##season_id##", additionalInfo.seasonId);
            twitterUrl = twitterUrl.replace("##event_id##", eventInfo.id);
            scope.find("a.btn-tweet").attr("href", twitterUrl);
            //
            var statsUrl;
            if (additionalInfo.statcrewSportId !== undefined && eventInfo.statsApp != null) {
                if (eventInfo.statsApp === "STATSENTRY_LIVE" || eventInfo.statsApp === "STATSENTRY_SCORESHEET") {
                    statsUrl = scope.find("a.btn-stats-game").attr("href");
                    statsUrl = statsUrl.replace("##season_id##", additionalInfo.seasonId);
                    statsUrl = statsUrl.replace("##event_id##", eventInfo.id);
                    statsUrl = statsUrl.replace("##sport_code##", additionalInfo.statcrewSportId);
                    statsUrl = statsUrl.replace("##event_date##", ps.gameday.controller.selectedDate.format("MM/DD/YYYY"));
                }
                if (eventInfo.statsApp === "PRESTOSTATS") {
                    statsUrl = "/action/stats/prestostats/statGame.jsp?event_id=" + eventInfo.id;
                }
            }
            if (statsUrl) {
                scope.find("a.btn-stats-game").attr("href", statsUrl);
            } else {
                scope.find("a.btn-stats-game").remove();
            }
        } else {
            scope.find(".title .text-view-event").attr("href", scope.find(".title" +
                    " .text-view-event").attr("href").replace("/event/", "/eventm/") + "&season_id=" + additionalInfo.seasonId);
            scope.find(".title .btn-edit-event").attr("href", scope.find(".title" +
                    " .btn-edit-event").attr("href").replace("/schedule/", "/schedulem/") + "&season_id=" + additionalInfo.seasonId);
        }
    };

    /* Listeners */
    /**
     * Score click listener
     */
	var scoreClick = function() {
        var eventIndex = $(this).parents(".event").data("index");
        var seasonIndex = $(this).parents(".season-container").data("index");

        var season = cachedData[selectedDateString()][seasonIndex];
        var event = cachedData[selectedDateString()][seasonIndex].events[eventIndex];

        ps.gameday.scorePopup.controller.show(event, season, doneSendScore);
	};

    /**
     * Update results click listener
     */
	var updateResultClick = function() {
        var eventIndex = $(this).parents(".event").data("index");
        var seasonIndex = $(this).parents(".season-container").data("index");

        var season = cachedData[selectedDateString()][seasonIndex];
        var event = cachedData[selectedDateString()][seasonIndex].events[eventIndex];

        ps.gameday.resultPopup.controller.show(event, season, doneSendScore);
	};

    /**
     * Done SendScore function
     * @param season season data from cache
     * @param event event data from cache
     * @returns {Function} Done function for use in $.ajax
     */
    var doneSendScore = function(season, event){
        return function(data, textStatus, jqXHR) {
            if (data.error === undefined) {
                event.statusFormatted = data.statusFormatted;
                updateRowUi(season, event);
            }
        }
    };

    /**
     * Updates an event row when the user changes the score.
     * @param season season data from cache
     * @param event event data from cache
     */
    var updateRowUi = function(season, event) {
        var eventTemplate = $(".templates .event-template");
        var seasonContainer = $('.all-rows .season-container[data-id="'
            + season.id + '"]');
        var eventRow = $(".season-container[data-id='" + season.id + "']").find(".event[data-id='" + event.id + "']");

        var additionalInfo = {};
        additionalInfo.seasonId = season.id;
        additionalInfo.isH2H = seasonContainer.hasClass("h2h");
        additionalInfo.statcrewSportId = seasonContainer.attr("data-statcrewSportId");
        additionalInfo.index = eventRow.index();

        var eventItem = buildEventItem(eventTemplate, event, additionalInfo);
        buildEventLegends(event, eventItem);
        buildSeasonLegends(seasonContainer);
        // Replace row.
        eventRow.replaceWith(eventItem);
    };

    /**
     * Filter by Sport listener
     * Filters in the current view/date
     */
    var filterBySport = function() {
        var elementsToShow;
        if (ps.gameday.controller.selectedSport == null) {
            elementsToShow = $(".all-rows .season-container:not(.no-events)");
            elementsToShow.fadeIn("fast");
        } else {
            $(".all-rows .season-container:not(.no-events)[data-statcrewSportId!='" + ps.gameday.controller.selectedSport + "']").hide();
            elementsToShow = $(".all-rows .season-container:not(.no-events)[data-statcrewSportId='" + ps.gameday.controller.selectedSport + "']");
        }
        if (!showsHiddenSeasons) {
            elementsToShow = elementsToShow.filter(":not(.hidden-season)");
        }
        elementsToShow.fadeIn("fast");
        if (elementsToShow.length == 0) {
            $(".no-events-container").fadeIn("fast");
        } else {
            $(".no-events-container").hide();
        }
    };

    /* End Listeners */

    /**
     * Display no data for a date
     */
    var displayNoData = function(dateString) {
    	var dateItem = $(".dates .date-item[data-date='" + dateString + "']");
    	var numberEventsContainer = dateItem.find(".number-events");
    	numberEventsContainer.find(".number").text(0);
    	numberEventsContainer.find(".text").removeClass("hide");
    	numberEventsContainer.find(".loading-number-events").hide();
        $(".no-events-container").fadeIn("fast");
    	ps.bootstrapExtensions.loadingModal.hide();
    }

    /**
     * Cache seasons and then events for a given date
     * @param date a date to cache (MomentJs)
     */
    var doCacheForDay = function(date) {
        var dateString = date.format("MM/DD/YYYY");
        var dateItem = $(".dates .date-item[data-date='" + dateString + "']");

        if (!isDayCached(dateString)) {
            $.ajax({
                url: "/admin/team/gameday/seasonListByDate.json",
                data: {
                    date: dateString
                },
                dataType: "json"
            }).done(function (seasonData, textStatus, jqXHR) {
                cachedData[dateString] = [];
                var seasonsProcessed = {};
                seasonsProcessed.count = 0;
                if (seasonData.length == 0) {
                	displayNoData(dateString);
                } else {
	                $(seasonData).each(function(index, value) {
	                    if (cachedData[dateString][index] === undefined) {
	                        value.fetched = moment();
	                        cachedData[dateString][index] = value;
	                    }
	                    $.ajax({
	                        url: "/admin/team/gameday/seasonEvents.json",
	                        data: {
	                            seasonId: value.id,
	                            date: dateString
	                        },
	                        dataType: "json"
	                    })
	                    .done(doneCacheEventFunction(cachedData[dateString][index], dateItem, seasonsProcessed, seasonData.length));
	                });
                }
            })
        } else {
            var seasonsQuantity = cachedData[dateString].length;
            $(cachedData[dateString]).each(function (index, season) {
                updateNumberEventsForDate(season.events, dateItem, index == (seasonsQuantity - 1));
            });
        }
    };

    /**
     * Done function for caching event
     * @param cached season cached object (for a date)
     * @param dateItem dateItem (jQuery obj) from date selector
     * @param seasonsProcessed Quantity of season processed
     * @param seasonsQuantity Total
     * @returns {Function} Done function for use in $.ajax
     */
    var doneCacheEventFunction = function(cached, dateItem, seasonsProcessed, seasonsQuantity) {
        return function(data, textStatus, jqXHR) {
            cached.events = data;
            seasonsProcessed.count++;
            updateNumberEventsForDate(cached.events, dateItem, seasonsProcessed.count == seasonsQuantity);
        }
    };

    /**
     * Updates "# events" legend in date selector.
     * @param data
     * @param dateItem dateItem (jQuery) from date selector
     * @param displayData boolean, if it's true displays the legend
     */
    var updateNumberEventsForDate = function(events, dateItem) {
        if (events === undefined) { events = []; }
        //
        var numberEventsContainer = dateItem.find(".number-events");
        var numberEvents = parseInt(numberEventsContainer.find(".number").text(), 10);
        numberEventsContainer.find(".number").text(numberEvents + events.length);
        updateMissingInfoIcon(dateItem.data().date);
    };

    /**
     * Collapse or expand a season container
     */
    var toggleCollapse = function() {
        var button = $(this);
        var seasonContainer = button.parents(".season-container")
        var content = seasonContainer.find(".content-container");
        var icon = button.find("span");
        if (content.hasClass("collapsed")) {
            expandSeasonContainer(seasonContainer);
            populateEvents(seasonContainer[0].dataset.id, cachedData[selectedDateString()][seasonContainer[0].dataset.index]);
        } else {
            content.addClass("collapsed");
            content.fadeOut("fast");
            icon.addClass("glyphicon-chevron-down")
                .removeClass("glyphicon-chevron-up");
            button.data("original-title", "MAXIMIZE")
                .attr("title", "MAXIMIZE")
                .tooltip('fixTitle')
                .tooltip('setContent');
        }
    };

    function expandSeasonContainer(seasonContainer) {
        var content = seasonContainer.find(".content-container");
        var button = seasonContainer.find(" .title-container .title .right-button");
        var icon = button.find("span");
        content.removeClass("collapsed");
        content.fadeIn("fast");
        icon.removeClass("glyphicon-chevron-down")
            .addClass("glyphicon-chevron-up");
        button.data("original-title", "MINIMIZE")
            .attr("title", "MINIMIZE")
            .tooltip('fixTitle')
            .tooltip('setContent');
    }

    /**
     * Toggles hide or unhide a season
     */
    var toggleSeasonHide = function() {
        var element = $(this);
        var seasonContainer = element.parents(".season-container");
        var button = seasonContainer.find(".btn-hide-season");
        var buttonSpan = button.find("span");
        var loading = seasonContainer.find(".loading-season");
        loading.show();
        if (buttonSpan.hasClass("glyphicon-eye-close")) {
            buttonSpan.removeClass("glyphicon-eye-close");
            buttonSpan.addClass("glyphicon-eye-open");
            toggleSeasonHideTooltip(button, true);
            unHideSeason(seasonContainer);
        } else {
            buttonSpan.removeClass("glyphicon-eye-open");
            buttonSpan.addClass("glyphicon-eye-close");
            toggleSeasonHideTooltip(button, false);
            hideSeason(seasonContainer);
        }
    };

    var toggleSeasonHideTooltip = function(button, isNotHidden) {
        if (isNotHidden) {
            button.data("original-title", "HIDE SEASON")
                .attr("title", "HIDE SEASON")
                .tooltip('fixTitle')
                .tooltip('setContent');
        } else {
            button.data("original-title", "UNHIDE SEASON")
                .attr("title", "UNHIDE SEASON")
                .tooltip('fixTitle')
                .tooltip('setContent');
        }
    };

    /**
     * Hide season
     * @param seasonContainer jQuery obj
     */
    var hideSeason = function(seasonContainer) {
        seasonContainer.addClass("hidden-season");
        if (!showsHiddenSeasons) {
            seasonContainer.fadeOut("fast");
        }
        $(".show-hide-seasons-container").fadeIn("fast");
        // setTimeout needed because fadeIn('fast') took 200 millis to hide
        // the container
        setTimeout(checkNoVisibleEvents, 250);
        // Do call
        var data = {};
        data.seasonId = seasonContainer.data("id");
        data.hidden = true;
        //
        toggleHideCall(data, seasonContainer.data("index"));
    };

    /**
     * Unhide season
     * @param seasonContainer jQuery obj
     */
    var unHideSeason = function(seasonContainer) {
        seasonContainer.removeClass("hidden-season");
        if (!showsHiddenSeasons) {
            seasonContainer.fadeIn("fast");
        }
        if ($(".all-rows .season-container.hidden-season:not(.no-events)").length == 0) {
            $(".show-hide-seasons-container").fadeOut("fast");
        }
        // setTimeout needed because fadeIn('fast') took 200 millis to hide
        // the container
        setTimeout(checkNoVisibleEvents, 250);
        //
        var dataHideCall = {};
        dataHideCall.seasonId = seasonContainer.data("id");
        dataHideCall.hidden = false;
        //
        toggleHideCall(dataHideCall, seasonContainer.data("index"));
    };

    /**
     * Toggle hide ajax call (push changes to server)
     * @param dataHideCall {seasonId, hidden}
     * @param seasonIndex index of the season in .all-rows container.
     */
    var toggleHideCall = function(dataHideCall, seasonIndex) {
        $.ajax({
            url: "/admin/team/gameday/setHiddenSeason.jsp",
            method: "POST",
            data: dataHideCall
        }).done(doneHide(dataHideCall.seasonId, seasonIndex, dataHideCall.hidden));
    };

    /**
     * Done function for ajax call and update the seasonContainer.
     * @param seasonId
     * @returns {Function} Done function for use in $.ajax
     */
    var doneHide = function(seasonId, seasonIndex, isHidden) {
        return function(data, textStatus, jqXHR) {
            var seasonContainer = $('.all-rows .season-container[data-id="'
                + seasonId + '"]');
            var loading = seasonContainer.find(".loading-season");
            cachedData[selectedDateString()][seasonIndex].hidden = isHidden;
            loading.hide();
            if(onSeasonHiddenCallback){
                onSeasonHiddenCallback(seasonId);
            };
        }
    };

    /**
     * Check if there is no events to display, shows no events message.
     */
    var checkNoVisibleEvents = function() {
        if ($(".season-container").length === 0) {
            $(".no-events-container").fadeIn("fast");
        } else {
            $(".no-events-container").hide();
        }
    };

    /**
     * Shows or hides hidden seasons.
     */
    var toggleShowOrHidesSeasons = function() {
        showsHiddenSeasons = !showsHiddenSeasons;
        var seasons = $(".all-rows .season-container.hidden-season:not(.no-events)");
        if(showsHiddenSeasons){
            seasons.fadeIn("fast");
        }else{
            seasons.fadeOut("fast");
        }
        checkNoVisibleEvents();

        ps.gameday.utils.hideFilters();
    };

    /**
     * Verifies if the day is cached
     * @param dateString date value formatted as String MM/DD/YYYY
     * @returns {boolean} true if it's cached, false if it's not.
     */
    var isDayCached = function(dateString) {
        if (cachedData[dateString] !== undefined &&
            cachedData[dateString][0] !== undefined &&
            cachedData[dateString][0].fetched.isAfter(moment().subtract(10, "minutes"))) {
            return true;
        }
        return false;
    };

    /**
     * Format a String value with separator and check if it's null
     * @param value
     * @param separator
     * @returns {String} separator + value or if it's null returns String.EMPTY
     */
    var checkNullAndFormatValue = function(value, separator) {
        if (value != null) {
            return separator + value;
        }
        return "";
    };

    /**
     * Indicates if a manual schedule event has been set with a manual status of Final
     * @param manualEvent
     * @returns {boolean}
     */
    var isManualScheduleEventSetToFinal = function(manualEvent){
        return /^final/i.test(manualEvent.statusFormatted);
    };

    var hasResult = function(event) {
      // Check class SeasonSportSharing for see enum values  
      if (event.seasonSportSharing === 3) {
          // Meet events has only away team
          return (event.awayResult !== null);
      } else {
          return (event.awayResult && event.homeResult);
      }
    };
    
    var onSeasonHiddenCallback = null;

    var onSeasonHidden = function(callback){
        onSeasonHiddenCallback = callback;
    };

	return {
        todayDate:todayDate,
        selectedDate : selectedDate,
        selectedSport:selectedSport,
		buildDates : buildDates,
        populateSeasons : populateSeasons,
        scoreClick : scoreClick,
		updateResultClick : updateResultClick,
        filterBySport: filterBySport,
        toggleShowOrHidesSeasons:toggleShowOrHidesSeasons,
        onSeasonHidden: onSeasonHidden
	}
})(jQuery);
