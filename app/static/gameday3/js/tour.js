var ps = ps || {};
ps.gameday = ps.gameday || {};

ps.gameday.tour = (function(admin, gamedayController) {
    'use strict';

    var init = function(){
        var tour = admin.getTourInstance({
            steps: [
                {
                    element: ".filters-toggle:visible",
                    title: "Event filters",
                    content: "Here you can access filter options for the season events",
                    placement: 'bottom'
                },
                {
                    element: ".show-hide-seasons-button:visible",
                    title: "Display hidden seasons",
                    content: "When this button appears, it indicates there are seasons hidden by the user. Press this button to show or hide hidden seasons.",
                    placement: 'bottom'
                },
                {
                    element: ".dates",
                    title: "Event dates",
                    content: "These are the event dates. The one in the middle is the date you selected.",
                    placement: 'bottom'
                },
                {
                    element: ".season-container:not( [style*='display: none'] ):first .season-name",
                    title: "Manage season",
                    content: "You can manage the entire season by clicking on the season name.",
                    placement: 'auto bottom'
                }
            ]
        });

        // Initialize the tour
        tour.init();

        // Start the tour
        tour.start();

        // If the tour is in the last step, start again from the beginning
        var lastStepIndex = tour._options.steps.length - 1;
        if(tour.getCurrentStep() === lastStepIndex){
            tour.goTo(0);
        }

        gamedayController.onSeasonHidden(function(){
            if(tour.getCurrentStep() === lastStepIndex){
                tour.goTo(0);
            }
        });

        return tour;
    }

    return {
        init: init
    }
})(ps.admin, ps.gameday.controller);
