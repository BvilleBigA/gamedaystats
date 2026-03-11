function unescapeHTML(html) {
    var htmlNode = document.createElement("DIV");
    htmlNode.innerHTML = html;
    if (htmlNode.innerText != undefined)
        return htmlNode.innerText; // IE
    return htmlNode.textContent; // FF
}

function saveFilesAsZip(fileNameArray, fileDataArray) {
  var zip = new JSZip();
  fileNameArray.forEach(function (value, index, array) {
    var fileName = value;
    var fileData = fileDataArray[index];      
    zip.file(fileName, fileData);
  });
  zip.generateAsync({type:"blob"}).then(function (blob) {
    saveAs(blob, "StatsEntry.zip");
  });
}

function saveFilesAs(fileName, fileData) {
    var blob = new Blob([fileData], {type: "text/plain;charset=utf-8"});
    saveAs(blob, fileName);
}