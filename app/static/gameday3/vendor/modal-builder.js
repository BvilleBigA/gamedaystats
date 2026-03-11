/**
 * Created by villo on 10/3/16.
 *
 * This builder is to create a modal popup using bootstrap, without adding
 * anything to markup.
 *
 * If you want an icon in title, please use "type" enum (info, error or
 * question), it uses glyphicon.
 *
 * If you want a larger or smaller popup, please use "size" enum (small, large).
 *
 * Optional properties:
 *      - size (enum)
 *      - type (enum)
 *      - closeButtonInHeader (boolean, default value: false).
 *
 * ====================
 * Click Example:
 * ====================
 *
     ps.bootstrapExtensions.modalBuilder.build(
     {
         title: "Information",
         size: modalBuilder.size.small,
         type: modalBuilder.type.info,
         closeButtonInHeader: true,
         content: "This is the main content of the popup.",
         buttons: [
             { text: "Cancel",
               type: "button",
               className: "btn-default btn-cancel",
               close: true
             },
             { text: "Refresh",
               type: "button",
               className: "btn-primary btn-refresh",
               click:
                 function(contentBody) {
                     // You can get values from inputs in content using
                      contentBody parameter
                     var username = contentBody.find("#username").val();

                     $(".information").html("Done!");
                 }
             }]
     });
     ps.bootstrapExtensions.modalBuilder.show();
 *
 *
 * ====================
 * Submit Example (you need to add a form in the content to use validation)
 * ====================
 *
 * You need to add a form in content. You can also use validation from
 * http://1000hz.github.io/bootstrap-validator/
 *
 * Dependencies for validation:
 *      <script type="text/javascript" src="/info/bootstrap/plugins/validator/validator.js"></script>
 *
 *
     ps.bootstrapExtensions.modalBuilder.build(
     {
         title: "Information",
         size: modalBuilder.size.small,
         type: modalBuilder.type.info,
         closeButtonInHeader: true,
         content: "<form>Hi there!<input type='number'
          placeholder='score'></form>",
         buttons: [
             { text: "Cancel",
               type: "button",
               className: "btn-default btn-cancel",
               close: true
             },
             { text: "Refresh",
               type: "submit",
               className: "btn-primary btn-refresh"
             }],
             submit: function(e) {
                 // You can get values from inputs in content using
                  contentBody parameter
                 var content = $(e.target).parent();

                 var username = content.find("#username").val();

                 // do Ajax call...
             },
             validationOptions: {
                custom: {
                    requiredStartedGame: function($el) {
                        var form = $($el).parents("form");
                        var status = form.find("#status");
                        if (isNotValid) {
                                return false;
                        } else {
                            return true;
                        }
                    }
                },
                errors: {
                    requiredStartedGame: "Please fill out this field with numbers"
                }
            }
     });
     ps.bootstrapExtensions.modalBuilder.show();
 *
 *   validationOptions is optional, you can set up custom validations or
 *   different options, more info: http://1000hz.github.io/bootstrap-validator/#validator-options
 *
 */

var ps = ps || {};
ps.bootstrapExtensions = ps.bootstrapExtensions || {};

ps.bootstrapExtensions.modalBuilder = (function($) {
    'use strict';

    var modalTemplate =
        "<div class='modal fade modalTemplate' role='dialog'>" +
            "<div class='modal-dialog'>" +
                "<div class='modal-content'>" +
                    "<div class='modal-header'>" +
                        "<h4 class='modal-title'></h4>" +
                    "</div>" +
                    "<div class='modal-body'></div>" +
                    "<div class='modal-footer'></div>" +
                "</div>" +
            "</div>" +
        "</div>";
    var iconTemplate = "<span class='glyphicon' aria-hidden='true'></span>";
    var buttonTemplate = "<button class='btn'></button>";
    var closeButtonTemplate = "<button type='button' class='close' data-dismiss='modal' aria-label='Close'><span aria-hidden='true'>&times;</span></button>";
    var type = {
        info: "glyphicon-exclamation-sign",
        error: "glyphicon-remove-sign",
        question: "glyphicon-question-sign"
    };
    var size = {
        small: "modal-sm",
        normal: "modal-md",
        large: "modal-lg"
    };

    var backdrop = null;
    
    return {
        size: size,
        type: type,
        initialize: function () {
            if ($(".modalTemplate").length == 0) {
                $("body").append(modalTemplate);
                $(".modalTemplate").on("shown.bs.modal", function(){
                    backdrop = $(".modal-backdrop");
                });
                $(".modalTemplate").on("hidden.bs.modal", function(){
                    if(backdrop){
                        $(backdrop).remove();
                    }
                });
            }
        },
        clear: function () {
            var modal = $(".modalTemplate");
            modal.find(".modal-dialog").removeAttr("class").addClass("modal-dialog");
            modal.find(".modal-header button").remove();
            modal.find(".modal-title").empty();
            modal.find(".modal-body").empty();
            modal.find(".modal-footer").empty();
        },

        build: function (config) {
            this.initialize();
            this.clear();
            var modal = $(".modalTemplate");
            var title = modal.find(".modal-title");
            var body = modal.find(".modal-body");
            var footer = modal.find(".modal-footer");

            if (config.size !== undefined) {
                modal.find(".modal-dialog").addClass(config.size);
            }
            if (config.closeButtonInHeader !== undefined && config.closeButtonInHeader) {
                modal.find(".modal-header").prepend(closeButtonTemplate);
            }

            var titleHtml = config.title;
            if (config.type !== undefined) {
                var icon = $(iconTemplate).clone();
                icon.addClass(config.type);

                titleHtml = icon.prop("outerHTML") + "&nbsp;" + titleHtml;
            }

            title.html(titleHtml);
            body.html(config.content);
            if (config.buttons !== undefined) {
                $.each(config.buttons, function (index, value) {
                    var buttonHtml = $(buttonTemplate).clone();
                    $(buttonHtml).html(value.text);
                    $(buttonHtml).attr("type", value.type);
                    $(buttonHtml).addClass(value.className);
                    if (value.click !== undefined) {
                        $(buttonHtml).click(function() {
                            value.click(body);
                        });
                        // Adds same click event for close button in header.
                        if (value.close && config.closeButtonInHeader) {
                            modal.find(".modal-header > .close").click(function() {
                                value.click(body);
                                modal.modal("hide");
                            });
                        }
                    }
                    if (value.close) {
                        $(buttonHtml).click(function() {
                            modal.modal("hide");
                        });
                    }
                    if (value.type == 'submit') {
                        $(buttonHtml).click(function() {
                            body.find("form").submit();
                        });
                    }
                    footer.append(buttonHtml);
                });
            }
            if (config.submit !== undefined) {
                var form = body.find("form");
                if (form.validator != null) {
                    form.validator(config.validationOptions).submit(function(e) {
                        // Force Validation
                        $(e.target).validator('validate');
                        $(e.target).find("input").focusout();
                        if ($(e.target).find(".has-error").length > 0) {
                            return false;
                        }
                    });
                }
                form.submit(config.submit);
            }
        },

        show: function () {
            $(".modalTemplate").modal("show");
        },

        hide: function() {
            $(".modalTemplate").modal("hide");
        },
        
        preventClose: function() {
            var modal = $(".modalTemplate");

            modal.data('bs.modal').options.keyboard = false;
            modal.data('bs.modal').options.backdrop = 'static';
        },
        
        enableClose: function() {
            var modal = $(".modalTemplate");
            modal.data('bs.modal').options.keyboard = true;
            modal.data('bs.modal').options.backdrop = true;
        }
    }
})(jQuery);