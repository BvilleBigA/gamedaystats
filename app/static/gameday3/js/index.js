/**
 * Created by villo on 20/5/16.
 */

var ps = ps || {};
ps.gameday = ps.gameday || {};

ps.gameday.index = (function($) {
    'use strict';

    var selectedView = "list";
    var datepicker;
    var params = {};

    /**
     * Initialization for gameday page
     */
    var init = function() {
        $(document).ready(function() {
            ps.gameday.controller.selectedDate = ps.gameday.controller.todayDate = moment();
            params = $.getHashParameters();
            if (params.date !== undefined && $.trim(params.date) != "") {
                ps.gameday.controller.selectedDate = moment(params.date, "MM/DD/YYYY");
            }
            if (params.sport !== undefined && $.isNumeric(params.sport)) {
                ps.gameday.controller.selectedSport = parseInt(params.sport, 10);
            }
            datepicker = $(".right-menu-container div.datepicker");
            var datepickerInstance = datepicker.data("DateTimePicker");
            datepicker.on("dp.change", function (e) {
                if (e.oldDate != null && e.date.format("L") == e.oldDate.format("L")) {
                    return;
                }

                ps.gameday.controller.selectedDate = $(this).data("DateTimePicker").date();
                params.date = ps.gameday.controller.selectedDate.format("MM/DD/YYYY");
                $.setHashParameters(params);
                ps.gameday.utils.hideFilters();
                //
                ps.gameday.controller.buildDates(ps.gameday.controller.selectedDate);
                ps.gameday.controller.populateSeasons();
            });

            datepicker.on("dp.show", function(){
                $(".datepicker-days td.day").on("click", function(){
                    ps.gameday.utils.hideFilters();
                });
            });

            // This fix the issue when you use back button from different url.
            if(datepickerInstance && datepicker){
                if (ps.gameday.controller.selectedDate.isSame(datepickerInstance.date())) {
                    datepicker.trigger("dp.change");
                } else {
                    datepicker.data("DateTimePicker").date(ps.gameday.controller.selectedDate);
                }
            }

            $(".btn-today").unbind("click")
                           .click(function() {
                               $(this).parent().data("DateTimePicker").date(ps.gameday.controller.todayDate);
                               ps.gameday.utils.hideFilters();
                           });

            $(".change-view-container a").click(toggleView);
            //
            $(".sport-selector li a").click(function() {
                var sportId = $(this).attr("data-sport-id");
                var oldSelectedSport = ps.gameday.controller.selectedSport;
                if (sportId === undefined) {
                    ps.gameday.controller.selectedSport = null;
                } else {
                    ps.gameday.controller.selectedSport = sportId;
                }
                if (oldSelectedSport != ps.gameday.controller.selectedSport) {
                    params.sport = ps.gameday.controller.selectedSport;
                    $.setHashParameters(params);
                    ps.gameday.controller.filterBySport();
                }
                ps.gameday.utils.hideFilters();
            });

            $(".show-hide-seasons-button").click(ps.gameday.controller.toggleShowOrHidesSeasons);

            $(".event-actions").appendTo($(".nav2 .more-actions"));
            $(".filters-toggle").click(function(){
                $('.filters-container').toggleClass('active');
            });

            $(window).resize(resize).resize();
            $(window).on('hashchange', hashChange);
        });
    };

    /**
     * Changes the view between grid or list. Also if the screen is too small,
     * it forces the view to grid.
     */
    var toggleView = function() {
        var allRowsContainer = $(".all-rows");
        var idClickedButton = $(this).attr("id");
        if (idClickedButton == "list" && $(window).width() < 950) {
            return;
        }
        selectedView = idClickedButton;
        if (idClickedButton == "list" && allRowsContainer.hasClass("grid-view")) {
            $(this).addClass("btn-primary").removeClass("btn-default");
            $(this).next().removeClass("btn-primary").addClass("btn-default");
            //
            allRowsContainer.removeClass("grid-view").addClass("list-view");
        } else if (idClickedButton == "grid" && allRowsContainer.hasClass("list-view")) {
            $(this).addClass("btn-primary").removeClass("btn-default");
            $(this).prev().removeClass("btn-primary").addClass("btn-default");
            //
            allRowsContainer.removeClass("list-view").addClass("grid-view");
        }
    };

    /**
     * Resize logic to change the view from list to grid for mobile resolutions.
     */
    var resize = function() {
        if (selectedView != "list") {
            return;
        }
        var currentView = selectedView;
        if ($(window).width() < 950) {
            $(".change-view-container #grid").click();
            selectedView = currentView;
        } else if (selectedView != $(".change-view-container a[class='btn-primary']").attr("id")) {
            $(".change-view-container #" + selectedView).click();
            selectedView = currentView;
        }
    };

    var hashChange = function() {
        params = $.getHashParameters();
        if (params.date !== undefined && $.trim(params.date) != "") {
            ps.gameday.controller.selectedDate = moment(params.date, "MM/DD/YYYY");
        }
        datepicker.data("DateTimePicker").date(ps.gameday.controller.selectedDate);
    };

    return {
        init:init
    }

})(jQuery);

ps.gameday.index.init();
