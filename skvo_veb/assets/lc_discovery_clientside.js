window.dash_clientside = Object.assign({}, window.dash_clientside, {
    lcdSelect: {
        _perm: [],
        _rawPlotDiv: null,

        _rawPlotlyGraphDiv: function () {
            const root = document.getElementById('lc_discovery_graph');
            if (!root) {
                return null;
            }
            const plot = root.querySelector('.js-plotly-plot');
            if (plot && typeof plot.on === 'function') {
                return plot;
            }
            return null;
        },

        _serialiseAxisValue: function (value) {
            if (value instanceof Date) {
                return value.toISOString();
            }
            return value;
        },

        _permFromValue: function (raw) {
            if (raw === undefined || raw === null || raw === '') {
                return null;
            }
            const nested = Array.isArray(raw) ? raw[0] : raw;
            const n = Number(nested);
            return Number.isFinite(n) ? n : null;
        },

        _permFromEventPoint: function (point, plotDiv) {
            if (!point) {
                return null;
            }
            const fromId = window.dash_clientside.lcdSelect._permFromValue(point.id);
            if (fromId !== null) {
                return fromId;
            }
            const fromCustom = window.dash_clientside.lcdSelect._permFromValue(
                point.customdata
            );
            if (fromCustom !== null) {
                return fromCustom;
            }
            if (!plotDiv || !plotDiv.data) {
                return null;
            }
            const curve = point.curveNumber;
            const idx = (
                point.pointNumber !== undefined && point.pointNumber !== null
                    ? point.pointNumber
                    : point.pointIndex
            );
            const trace = plotDiv.data[curve];
            if (!trace || idx === undefined || idx === null) {
                return null;
            }
            if (Array.isArray(trace.ids) && trace.ids.length) {
                return window.dash_clientside.lcdSelect._permFromValue(trace.ids[idx]);
            }
            return null;
        },

        _selectedPointsForTrace: function (trace, permSet) {
            if (!trace || !Array.isArray(trace.ids) || !trace.ids.length) {
                return [];
            }
            const indices = [];
            for (let i = 0; i < trace.ids.length; i += 1) {
                const perm = window.dash_clientside.lcdSelect._permFromValue(
                    trace.ids[i]
                );
                if (perm !== null && permSet.has(perm)) {
                    indices.push(i);
                }
            }
            return indices;
        },

        _clearLassoOutline: function (plotDiv) {
            if (!plotDiv || typeof Plotly === 'undefined' || !Plotly.relayout) {
                return;
            }
            const update = {selections: []};
            const layout = plotDiv._fullLayout;
            if (
                layout
                && layout.xaxis
                && layout.xaxis.autorange === false
                && layout.xaxis.range
                && layout.xaxis.range.length === 2
            ) {
                update['xaxis.range'] = layout.xaxis.range.slice();
                update['xaxis.autorange'] = false;
            }
            if (
                layout
                && layout.yaxis
                && layout.yaxis.autorange === false
                && layout.yaxis.range
                && layout.yaxis.range.length === 2
            ) {
                update['yaxis.range'] = layout.yaxis.range.slice();
                update['yaxis.autorange'] = false;
            }
            Plotly.relayout(plotDiv, update);
        },

        _paint: function (plotDiv, permList, clearLasso) {
            if (!plotDiv || !plotDiv.data || typeof Plotly === 'undefined') {
                return;
            }
            const permSet = new Set();
            (permList || []).forEach(function (value) {
                const perm = window.dash_clientside.lcdSelect._permFromValue(value);
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            const values = plotDiv.data.map(function (trace) {
                return window.dash_clientside.lcdSelect._selectedPointsForTrace(
                    trace, permSet
                );
            });
            plotDiv.data.forEach(function (trace, index) {
                trace.selectedpoints = values[index];
            });
            if (typeof Plotly.restyle === 'function') {
                Plotly.restyle(plotDiv, {selectedpoints: values});
            } else if (typeof Plotly.redraw === 'function') {
                Plotly.redraw(plotDiv);
            }
            if (clearLasso) {
                window.dash_clientside.lcdSelect._clearLassoOutline(plotDiv);
            }
        },

        _paintSoon: function (plotDiv, permList) {
            const paint = function () {
                window.dash_clientside.lcdSelect._paint(plotDiv, permList, true);
            };
            paint();
            window.setTimeout(paint, 0);
            window.setTimeout(paint, 50);
            window.setTimeout(paint, 80);
        },

        _commitPerm: function (plotDiv, permList) {
            window.dash_clientside.lcdSelect._perm = permList;
            window.dash_clientside.lcdSelect._paintSoon(plotDiv, permList);
            if (typeof dash_clientside.set_props === 'function') {
                dash_clientside.set_props('store_lc_discovery_selected_perm', {
                    data: permList,
                });
            }
        },

        _unionEvent: function (plotDiv, evt, currentPerm) {
            const permSet = new Set();
            (currentPerm || []).forEach(function (value) {
                const perm = window.dash_clientside.lcdSelect._permFromValue(value);
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            if (!evt || !evt.points || !evt.points.length) {
                return Array.from(permSet);
            }
            evt.points.forEach(function (point) {
                const perm = window.dash_clientside.lcdSelect._permFromEventPoint(
                    point, plotDiv
                );
                if (perm !== null) {
                    permSet.add(perm);
                }
            });
            return Array.from(permSet);
        },

        _onSelectEvent: function (plotDiv, evt) {
            if (!evt || !evt.points || !evt.points.length) {
                return;
            }
            const next = window.dash_clientside.lcdSelect._unionEvent(
                plotDiv, evt, window.dash_clientside.lcdSelect._perm
            );
            window.dash_clientside.lcdSelect._commitPerm(plotDiv, next);
        },

        _ensureListeners: function (plotDiv) {
            if (!plotDiv) {
                return;
            }
            if (window.dash_clientside.lcdSelect._rawPlotDiv !== plotDiv) {
                window.dash_clientside.lcdSelect._rawPlotDiv = plotDiv;
                delete plotDiv._lcdSelectBound;
            }
            if (plotDiv._lcdSelectBound) {
                return;
            }
            plotDiv._lcdSelectBound = true;
            plotDiv.on('plotly_selected', function (evt) {
                const live = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
                window.dash_clientside.lcdSelect._onSelectEvent(live || plotDiv, evt);
            });
            plotDiv.on('plotly_click', function (evt) {
                const live = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
                window.dash_clientside.lcdSelect._onSelectEvent(live || plotDiv, evt);
            });
        },

        _snapshotZoom: function (plotDiv, timeAxis, domain, phaseOn) {
            const layout = plotDiv && plotDiv._fullLayout;
            if (!layout || !layout.xaxis || !layout.yaxis) {
                return null;
            }
            const serial = window.dash_clientside.lcdSelect._serialiseAxisValue;
            const xa = layout.xaxis;
            const ya = layout.yaxis;
            const next = {
                axis: timeAxis || 'mjd',
                domain: domain || 'flux',
                phase: !!phaseOn,
            };
            if (
                xa.autorange === true
                || !xa.range
                || xa.range.length !== 2
            ) {
                next.x_autorange = true;
            } else {
                next.x_autorange = false;
                next.x0 = serial(xa.range[0]);
                next.x1 = serial(xa.range[1]);
            }
            if (
                ya.autorange === true
                || ya.autorange === 'reversed'
                || !ya.range
                || ya.range.length !== 2
            ) {
                next.y_autorange = true;
            } else {
                next.y_autorange = false;
                next.y0 = serial(ya.range[0]);
                next.y1 = serial(ya.range[1]);
            }
            return next;
        },

        _zoomFromRelayout: function (relayoutData, current, timeAxis, domain, phaseOn) {
            const next = Object.assign({}, current || {}, {
                axis: timeAxis || 'mjd',
                domain: domain || 'flux',
                phase: !!phaseOn,
            });
            const xAuto = relayoutData['xaxis.autorange'];
            const yAuto = relayoutData['yaxis.autorange'];
            if (xAuto === true) {
                next.x_autorange = true;
                delete next.x0;
                delete next.x1;
            } else if (
                relayoutData['xaxis.range[0]'] !== undefined
                && relayoutData['xaxis.range[1]'] !== undefined
            ) {
                next.x_autorange = false;
                next.x0 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['xaxis.range[0]']
                );
                next.x1 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['xaxis.range[1]']
                );
            } else if (
                Array.isArray(relayoutData['xaxis.range'])
                && relayoutData['xaxis.range'].length === 2
            ) {
                next.x_autorange = false;
                next.x0 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['xaxis.range'][0]
                );
                next.x1 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['xaxis.range'][1]
                );
            }
            if (yAuto === true || yAuto === 'reversed') {
                next.y_autorange = true;
                delete next.y0;
                delete next.y1;
            } else if (
                relayoutData['yaxis.range[0]'] !== undefined
                && relayoutData['yaxis.range[1]'] !== undefined
            ) {
                next.y_autorange = false;
                next.y0 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['yaxis.range[0]']
                );
                next.y1 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['yaxis.range[1]']
                );
            } else if (
                Array.isArray(relayoutData['yaxis.range'])
                && relayoutData['yaxis.range'].length === 2
            ) {
                next.y_autorange = false;
                next.y0 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['yaxis.range'][0]
                );
                next.y1 = window.dash_clientside.lcdSelect._serialiseAxisValue(
                    relayoutData['yaxis.range'][1]
                );
            }
            return next;
        },

        _domainFromMagSwitch: function (magOn) {
            return magOn ? 'mag' : 'flux';
        },

        bindGraph: function (figure, permList) {
            window.dash_clientside.lcdSelect._perm = Array.isArray(permList)
                ? permList
                : [];
            const attach = function () {
                const plotDiv = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
                window.dash_clientside.lcdSelect._ensureListeners(plotDiv);
                window.dash_clientside.lcdSelect._paint(
                    plotDiv, window.dash_clientside.lcdSelect._perm, false
                );
            };
            window.setTimeout(attach, 0);
            window.setTimeout(attach, 50);
            window.setTimeout(attach, 300);
            return window.dash_clientside.no_update;
        },

        mergeSelection: function (selectedData, clickData, currentPerm) {
            const triggered = dash_clientside.callback_context.triggered[0];
            if (!triggered) {
                return window.dash_clientside.no_update;
            }
            const triggerProp = triggered.prop_id.split('.')[1];
            const triggerData = triggerProp === 'selectedData'
                ? selectedData
                : clickData;
            if (!triggerData || !triggerData.points || !triggerData.points.length) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
            const base = (window.dash_clientside.lcdSelect._perm || []).concat(
                currentPerm || []
            );
            const next = window.dash_clientside.lcdSelect._unionEvent(
                plotDiv, triggerData, base
            );
            window.dash_clientside.lcdSelect._perm = next;
            window.dash_clientside.lcdSelect._paintSoon(plotDiv, next);
            return next;
        },

        clearSelection: function (nClicks) {
            if (!nClicks) {
                return window.dash_clientside.no_update;
            }
            const plotDiv = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
            window.dash_clientside.lcdSelect._perm = [];
            window.dash_clientside.lcdSelect._paintSoon(plotDiv, []);
            return [];
        },

        captureZoom: function (relayoutData, currentZoom, timeAxis, magOn, phaseOn) {
            if (!relayoutData) {
                return window.dash_clientside.no_update;
            }
            const keys = Object.keys(relayoutData);
            const hasAxis = keys.some(function (key) {
                return key.indexOf('xaxis') === 0 || key.indexOf('yaxis') === 0;
            });
            if (!hasAxis) {
                return window.dash_clientside.no_update;
            }
            const domain = window.dash_clientside.lcdSelect._domainFromMagSwitch(magOn);
            const plotDiv = window.dash_clientside.lcdSelect._rawPlotlyGraphDiv();
            const snapshot = window.dash_clientside.lcdSelect._snapshotZoom(
                plotDiv, timeAxis, domain, phaseOn
            );
            if (snapshot) {
                return snapshot;
            }
            return window.dash_clientside.lcdSelect._zoomFromRelayout(
                relayoutData, currentZoom, timeAxis, domain, phaseOn
            );
        },

        invalidateZoom: function (_timeAxis, _magOn, _phaseOn) {
            return null;
        },
    },
});
