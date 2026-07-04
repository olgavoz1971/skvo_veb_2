window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        clearInput: function clearInput(_, inputValue) {
            return null;
        },

        plotLightcurveFromStore: function(dataString, figure) {
            console.log('Updating figure from dcc.Store data');
//             console.log('dataString =', dataString);
            try {
                // Parse the JSON string stored in dcc.Store into an object
                let fullData = JSON.parse(dataString);
                // console.log('fullData =', fullData)
                // Extract the lightcurve DataFrame from the nested structure
                let lightcurve = fullData.lightcurve;
                // Extract metadata from the nested structure
                let metadata = fullData.metadata;

                //  lightcurve has the structure you get with pandas.to_dict(orient='split', index=False)
                if (Object.keys(lightcurve).length === 0) {
                    console.log('empty lightcurve');
                    return window.dash_clientside.no_update;
                }
                // console.log('lightcurve:', lightcurve);
                // const folded_view = lightcurve.folded_view; // Extract whether the folded view is active
                const folded_view = metadata.folded_view; // Extract whether the folded view is active.


                // Use destructuring to extract 'columns' and 'data' properties from the 'lightcurve' object.
                // 'columns' is now a _reference_ to lightcurve.columns, and 'rows' is a _reference_ to lightcurve.data.
                // Any changes to 'rows' or 'columns' will directly modify the 'lightcurve' object
                const { columns, data: rows } = lightcurve; // Extract columns and rows from the stored lightcurve.
                // console.log('rows =', rows);

                // Based on the folded_view status, determine which column to use for the x-axis.
                let xColIndex;
                let newX, xaxis_title
//                console.log('plotLightcurveFromStore: lightcurve', lightcurve)
//                console.log('plotLightcurveFromStore: metadata', metadata)
//                console.log('plotLightcurveFromStore: metadata.flux_unit', metadata.flux_unit)
//                console.log('plotLightcurveFromStore', lightcurve.hasOwnProperty('flux_unit'), lightcurve.flux_unit)
//                const yaxis_title = `flux, ${lightcurve.hasOwnProperty('flux_unit') ? lightcurve.flux_unit : ''}`;
                const yaxis_title = `flux, ${metadata.hasOwnProperty('flux_unit') ? metadata.flux_unit : ''}`;
                if (folded_view) {
                    xColIndex = columns.indexOf('phase');  // Use 'phase' if folded view is active
                    newX = rows.map(row => row[xColIndex]);
                    xaxis_title = `phase`;

                } else {
                    xColIndex = columns.indexOf('jd');     // Otherwise, use 'jd' for time
                    const jd0 = 2400000.5;
                    xaxis_title = `jd-${jd0}`;
                    newX = rows.map(row => row[xColIndex] - jd0);  // Subtract jd0 from each value
                }

                // Note: Here we use customdata field
                // customdata in go.Scatter (and other Plotly objects) is a user-defined field that allows to associate
                // additional data with each point on the graph. It doesn’t appear directly on the plot
                // but is accessible during interactions like clicks or selections.
                // Each entry in customdata corresponds to a point on the graph.
                // During interactions, customdata is included in the event objects (clickData, selectedData, etc.).

                // In this case, customdata is an array where the first element (customdata[0]) corresponds to a
                // unique identifier for each data point, such as its perm_index.

                // Extract the column indices for y-axis (flux), error (flux_err), customdata, and selection state
                // Get the indices of selected points from the customdata of the triggered event
                const yColIndex = columns.indexOf('flux');
                const yErrColIndex = columns.indexOf('flux_err');
                const customDataColIndex = columns.indexOf('perm_index');
                const selectedColIndex = columns.indexOf('selected');

                // Map the rows to extract the x (jd or phase), y (flux), error values, and customdata for each row
                // const newX = rows.map(row => row[xColIndex]);
                const newY = rows.map(row => row[yColIndex]);
                const newErrY = rows.map(row => row[yErrColIndex]);
                const newCustomData = rows.map(row => [row[customDataColIndex]]);

                // Determine which points are selected by checking where the 'selected' column equals 1
                const selectedPoints = rows
                    .map((row, index) => (row[selectedColIndex] === 1 ? index : null))
                    .filter(index => index !== null);  // Filter out any null values (non-selected rows)

                // console.log('selectedPoints =', selectedPoints);

                // Update the figure data:
                const newData = figure.data.map(trace => {
                    return {
                        ...trace,
                        x: newX,          // Update x values (jd or phase).
                        y: newY,          // Update y values (flux).
                        error_y: { array: newErrY },  // Update error values.
                        customdata: newCustomData,    // Update customdata (perm_index).
                        selectedpoints: selectedPoints  // Highlight selected points.
                    };
                });
                // console.log('newData =', newData);

                // Copy the figure layout and remove any selections (e.g., lasso or box selection paths)
                const newLayout = { ...figure.layout,
                                    xaxis: { ...figure.layout.xaxis, title: xaxis_title},
                                    yaxis: { ...figure.layout.yaxis, title: yaxis_title}
                                  };
                delete newLayout.selections;        // remove lasso or box path

                // Return the updated figure with the new data and layout.
                const newFigure = { ...figure, data: newData, layout: newLayout };
                // console.log('newLayout:', newLayout);
                return newFigure;

            } catch (error) {
                // If there's an error, log it and prevent any update to the figure
                console.error("plotLightcurveFromStore Error:", error.message);
                return window.dash_clientside.no_update;
            }
        },

        updateFoldedView: function(phase_view, dataString) {
            console.log('Updating folded view based on phase_view:', phase_view);
            let fullData;
            try {
                // Parse the JSON data from the store
//                console.log('updateFoldedView: dataString =', dataString)
                fullData = JSON.parse(dataString);
                if (!fullData) {
                    return window.dash_clientside.no_update; // Prevent update if fullData is empty
                }
                // Ensure the necessary keys exist
                if (!fullData.hasOwnProperty('metadata')) {
                    console.error('updateFoldedView Error: Missing metadata in the stored data');
                    return window.dash_clientside.no_update;
                }
                // console.log('updateFoldedView: metadata =', fullData.metadata)
                // Update folded_view in metadata based on the phase_view input
                // Convert phase_view to integer (1 if not empty, otherwise 0)
                console.log('phase_view =', phase_view);
                // const folded_view = phase_view.length > 0 ? 1 : 0; // Check if phase_view has any selected values
                const folded_view = phase_view
                console.log('folded_view =', folded_view);

                // Update the metadata with the new folded_view value
                fullData.metadata.folded_view = folded_view;
                // console.log('Updated metadata:', fullData.metadata);

                // Return the updated dictionary as a JSON string
                return JSON.stringify(fullData);
            } catch (error) {
                console.error('updateFoldedView Error:', error);
                return window.dash_clientside.no_update;
            }
        },

        selectData: function (selectedData, clickData, dataString) {
            console.log("select_data");
            try {
                // dash_clientside.callback_context.triggered[0] contains information
                // on which input fired the callback (lasso or click)
                const triggered = dash_clientside.callback_context.triggered[0];

                if (!triggered) {
                    // If nothing triggered the callback, return no update
                    console.log("False callback 1");
                    return window.dash_clientside.no_update;
                }

                // Extracting the ID and property that triggered the callback
                console.log(`triggered.prop_id=${triggered.prop_id}`);
                const [trigger_id, trigger_prop] = triggered.prop_id.split('.'); // Splitting "id.property"
                console.log(`trigger_prop=${trigger_prop}`);

                // Determine whether the event was triggered by `selectedData` or `clickData`.
                let triggerData;
                if (trigger_prop === 'selectedData') {
                    // If lasso or box selection triggered the callback
                    triggerData = selectedData;
                } else {
                    // Otherwise, it was a click event
                    triggerData = clickData;
                }

                // If there's no actual data in the event, skip further processing
                if (!triggerData) {
                    console.log("False callback 2");
                    return window.dash_clientside.no_update;
                }

                // Parse the dataString which is expected to be a JSON string from dcc.Store
                // dataString has the structure: { lightcurve: {...}, metadata: {...} }
                let fullData = JSON.parse(dataString);
                let lightcurve = fullData.lightcurve; // Extracting the lightcurve data
                // console.log("!!!!!!!!! selectData: metadata", fullData.metadata)
                // console.log("lightcurve =", lightcurve);

                // Extract the columns and rows from the lightcurve (a table structure)
                // Use destructuring to extract 'columns' and 'data' properties from the 'lightcurve' object.
                // 'columns' is now a _reference_ to lightcurve.columns, and 'rows' is a _reference_ to lightcurve.data.
                // Any changes to 'rows' or 'columns' will directly modify the 'lightcurve' object
                const { columns, data: rows } = lightcurve;

                // Find the column index for the perm_index (unique permanent identifier for rows)
                const permIndexColumn = columns.indexOf('perm_index');

                // Map perm_index to the row index for quick lookup
                const permIndexMap = {};
                rows.forEach((row, index) => {
                    const permIndex = row[permIndexColumn];
                    permIndexMap[permIndex] = index;  // Create a mapping from perm_index to row index
                });
                // console.log("Map permIndexMap:", permIndexMap);

                // Get the indices of selected points from the customdata of the triggered event
                // console.log("triggerData =", triggerData);
                const selected_indices = triggerData.points.map(point => point.customdata[0]);
                // console.log("selected_indices =", selected_indices);

                // For each selected index, mark the corresponding point as selected in the table data
                selected_indices.forEach(index => {
                    if (index in permIndexMap) {
                        const rowIndex = permIndexMap[index];  // Find row index from the permIndexMap
                        rows[rowIndex][columns.indexOf('selected')] = 1;  // Set 'selected' flag to 1
                        // console.log(`Updated the row ${rowIndex}:`, rows[rowIndex]);
                    }
                });
                // console.log("Renewed lightcurve:", lightcurve);

                // Update the fullData structure with the modified lightcurve
                fullData.lightcurve = lightcurve;
                // Return it as a JSON string to update the dcc.Store
                return JSON.stringify(fullData);

            } catch (error) {
                console.error("selectData Error:", error.message);
                return window.dash_clientside.no_update;
            }
        },

        unselectData: function (_, dataString) {
            console.log("unselect");
            try {
                if (!dataString) {
                    console.log("No data to unselect");
                    return window.dash_clientside.no_update;
                }

                // Parse the JSON string stored in dcc.Store into an object
                let fullData = JSON.parse(dataString);
                // console.log("parsed data for unselect =", fullData);
                const { columns, data: rows } = fullData.lightcurve;

                const selectedColumnIndex = columns.indexOf('selected');
                if (selectedColumnIndex === -1) {
                    console.error("unselectData: 'selected' column does not exist");
                    return window.dash_clientside.no_update;
                }

                rows.forEach(row => {
                    row[selectedColumnIndex] = 0;  // mark point as unselected
                });

                // console.log("All points unselected:", fullData.lightcurve);
                console.log("All points unselected");
                return JSON.stringify(fullData);
            } catch (error) {
                console.error("unselectData Error:", error.message);
                return window.dash_clientside.no_update;
            }
        },

        deleteSelected: function (deleteClick, dataString) {
            console.log("Delete selected points");
            try {
                if (!deleteClick) {
                    return window.dash_clientside.no_update;
                }
                // Parse the data from dcc.Store
                let fullData = JSON.parse(dataString);
                // console.log("deleteSelected:", fullData.metadata)
                const { columns, data: rows } = fullData.lightcurve;
                const selectedColIndex = columns.indexOf('selected');

                // Filter out rows where selected is 1
                const newRows = rows.filter(row => row[selectedColIndex] !== 1);

                // Update the data in dcc.Store
                // data.data.data = newRows;
                fullData.lightcurve.data = newRows;

                // console.log("Updated data (after deletion):", fullData.lightcurve);
                return JSON.stringify(fullData);
            } catch (error) {
                console.error("deleteSelected Error:", error.message);
                return window.dash_clientside.no_update;
            }
        },

        trimSelectedDisplayRange: function (n_clicks, selectionBounds, dataString, jd0) {
            console.log("trimSelectedDisplayRange");
            try {
                if (!n_clicks || !dataString) {
                    return window.dash_clientside.no_update;
                }
                if (!selectionBounds || selectionBounds.xmin === undefined || selectionBounds.xmax === undefined) {
                    console.error("trimSelectedDisplayRange: missing selection bounds");
                    return window.dash_clientside.no_update;
                }

                let left = Number(selectionBounds.xmin);
                let right = Number(selectionBounds.xmax);

                const leftJd = left + jd0;
                const rightJd = right + jd0;
                const fullData = JSON.parse(dataString);
                const { columns, data: rows } = fullData.lightcurve;
                const jdCol = columns.indexOf('jd');
                if (jdCol === -1) {
                    console.error("trimSelectedDisplayRange: jd column not found");
                    return window.dash_clientside.no_update;
                }

                fullData.lightcurve.data = rows.filter(row => {
                    const jd = Number(row[jdCol]);
                    return jd < leftJd || jd > rightJd;
                });

                return JSON.stringify(fullData);
            } catch (error) {
                console.error("trimSelectedDisplayRange Error:", error.message);
                return window.dash_clientside.no_update;
            }
        }
    }
});
