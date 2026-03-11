var cacheStatusValues = [];
cacheStatusValues[0] = 'uncached';
cacheStatusValues[1] = 'idle';
cacheStatusValues[2] = 'checking';
cacheStatusValues[3] = 'downloading';
cacheStatusValues[4] = 'updateready';
cacheStatusValues[5] = 'obsolete';
//
var progress="";

// Listeners for all possible events
var cache = window.applicationCache;
if (cache != null) {
    cache.addEventListener('cached', logEvent, false);
    cache.addEventListener('checking', logEvent, false);
    cache.addEventListener('downloading', logEvent, false);
    cache.addEventListener('error', handleCacheError, false);
    cache.addEventListener('noupdate', logEvent, false);
    cache.addEventListener('obsolete', logEvent, false);
    cache.addEventListener('progress', logEvent, false);
    cache.addEventListener('updateready', logEvent, false);
}
function logEvent(e) {
    var online, status, type, message;
    online = (isOnline()) ? 'yes' : 'no';
    status = cacheStatusValues[cache.status];
    type = e.type;

    message = 'online: ' + online;
    message += ', event: ' + type;
    message += ', status: ' + status;

    if(!navigator.onLine){
        return;
    }

    if (type == 'error' && navigator.onLine) {
        message += ". Error, the app couldn\'t be updated. PROGRESS: "+progress+" ERROR EVENT: "+JSON.stringify(e)+
                   "  CACHE: " + JSON.stringify(cache);
        callDebug(new Error(message),type,"Application cache error");

    } else {
        progress =  e.loaded+"/"+ e.total+" " ;
        callDebug(new Error(""),progress,"Application cache event");

        if (status == 'checking'){
            log("Checking for a new version.", 'red', true);
        }
        else if (status == 'downloading'){
            log("Updating to a newer version. The browser page will refresh automatically when the update is finished.", 'red', true);
        }
        else if (status == 'progress'){
            log("Updating to a newer version. The browser page will refresh automatically when the update is finished.", 'red', true);
        }
        else if (status == 'updateready'){
            log("Updating to a newer version. The browser page will refresh automatically when the update is finished. ", 'red', false);
        }
        else if (status == 'obsolete'){
            log("App is obsolete, the application cache for the site has been deleted. ", 'red', true);
        }
        else if (status == 'noupdate'){
            log('The app has not changed.');
        }
        else if (status == 'cached'){
            alert("READY.....");
            log('New version was successfully downloaded.');
        }
    }
}


function callDebug(exc,data,type){
    var debugObj = {} ;
    debugObj.type = type;
    debugObj.url = location.href;
    debugObj.exc = exc;
    debugObj.data = data;
    debugObj.stats_entry_event = "Application cache update";
    if(window._LTracker){
        window._LTracker.push(debugObj);
    }
}


function notifyError(message,type,status,online) {
    if(window.sendError)
        window.sendError(message,type,status);
}

function log(s, color, showRefresh) {
    if(window.logLoading)
        window.logLoading(s);
}


function logMsg(s) {
    if(window.logMsg)
        window.logMsg(s);
}


function isOnline() {
    return navigator.onLine;
}

// Swap in newly download files when update is ready

$(function() {
    if (window.applicationCache) {
        applicationCache.addEventListener('updateready', function(e) {
            try{
                if (window.applicationCache.status == window.applicationCache.UPDATEREADY) {
                    window.applicationCache.swapCache();
                    console.log("appcache updated");
                    window.location.reload();
                }
            }
            catch(exc){
                callDebug(exc,
                    'Update ready: ' +progress+" EVENT: "+JSON.stringify(e)+" CK: "+JSON.stringify(getCookies()) +" NAV:" +JSON.stringify(getNavigator),
                    "Swap cache error");
            }
        });
    }
});


if (cache != null) {
    cache.addEventListener('cached', function(e) {
        log("App files were successfully downloaded!!");
        if(window.swapReady){
            log("App files were successfully downloaded!!");
            window.swapReady();
            callDebug(new Error(""),"","App files were successfully downloaded!!");
        }
    }, false);
}

function handleCacheError(e) {
    var message = "The manifest returns 404 or 410, the download failed, "+
        "or the manifest changed while the download was in progress.";
    message += ". "+progress+
        " ERROR EVENT: "+JSON.stringify(e)+
        "  CACHE: " + JSON.stringify(cache);
    callDebug(new Error(message),"404 or 410","Application cache error");
};


// These two functions check for updates to the manifest file
function checkForUpdates() {
    if (cache != null) {
        log("Checking for updates...", 'green');
        cache.update();
    }
}

var getCookies = function(){
    var pairs = document.cookie.split(";");
    var cookies = {};
    for (var i=0; i<pairs.length; i++){
        var pair = pairs[i].split("=");
        cookies[pair[0]] = unescape(pair[1]);
    }
    return cookies;
}

var getNavigator = function(){
    var _navigator = {};
    for (var i in navigator) _navigator[i] = navigator[i];
    delete _navigator.plugins;
    delete _navigator.mimeTypes;
    return _navigator;

}