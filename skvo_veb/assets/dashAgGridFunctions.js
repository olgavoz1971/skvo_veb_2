// Discovery catalogue and shared Ag Grid value formatters (Dash AG Grid namespace).
// d3 is only available to inline {"function": "..."} formatters in columnDefs, not here.
var dagfuncs = (window.dashAgGridFunctions = window.dashAgGridFunctions || {});

/**
 * Returns true for null, blank, or non-finite numeric cell values.
 *
 * @param {*} value Raw grid cell value.
 * @returns {boolean} True when the cell should render as blank.
 */
function lcDiscoveryValueIsBlank(value) {
    if (value == null || value === '') {
        return true;
    }
    var numberValue = Number(value);
    return Number.isNaN(numberValue);
}

/**
 * Formats a numeric catalogue cell to a fixed decimal count for display only.
 *
 * @param {*} value Raw grid cell value.
 * @param {number} decimals Number of digits after the decimal point.
 * @returns {string} Formatted text or empty string.
 */
function lcDiscoveryFormatFixedDecimals(value, decimals) {
    if (lcDiscoveryValueIsBlank(value)) {
        return '';
    }
    return Number(value).toFixed(decimals);
}

dagfuncs.lcDiscoveryFmtSep = function (params) {
    return lcDiscoveryFormatFixedDecimals(params.value, 1);
};

dagfuncs.lcDiscoveryFmtRaDec = function (params) {
    return lcDiscoveryFormatFixedDecimals(params.value, 4);
};

dagfuncs.lcDiscoveryFmtMag = function (params) {
    return lcDiscoveryFormatFixedDecimals(params.value, 3);
};

dagfuncs.lcDiscoveryFmtMjd = function (params) {
    return lcDiscoveryFormatFixedDecimals(params.value, 1);
};

dagfuncs.lcDiscoveryFmtNPoints = function (params) {
    return lcDiscoveryFormatFixedDecimals(params.value, 0);
};
