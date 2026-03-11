/**
 * Created by villo on 19/5/16.
 */

jQuery.extend({
    getHashParameters : function(str) {
        if (document.location.hash ==  "") return {};
        return (str || document.location.hash).replace(/(^\#)/,'').split("&").map(function(n){return n = n.split("="),this[n[0]] = decodeURIComponent(n[1]),this}.bind({}))[0];
    },
    setHashParameters : function(params) {
        window.location.hash = decodeURIComponent($.param(params));
    }
});