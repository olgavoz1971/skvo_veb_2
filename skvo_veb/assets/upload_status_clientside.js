/**
 * Shared upload busy chip (Ticket 6).
 * Builds a Dash component tree matching skvo_veb.components.upload_status.
 */
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    skvoUpload: {
        busyCaption: function (filename) {
            const name =
                filename && String(filename).trim()
                    ? String(filename).trim()
                    : "file";
            return "Reading " + name + "\u2026";
        },

        buildBusyChip: function (
            contents,
            filename,
            nameTextClass,
            statusClass,
            iconClass,
            busyIcon,
            withIcon
        ) {
            if (!contents) {
                return window.dash_clientside.no_update;
            }
            const label = window.dash_clientside.skvoUpload.busyCaption(filename);
            const children = [];
            if (withIcon !== false) {
                children.push({
                    namespace: "dash_html_components",
                    type: "I",
                    props: {
                        className: ("bi " + busyIcon + " " + iconClass).trim(),
                    },
                });
            }
            children.push({
                namespace: "dash_html_components",
                type: "Span",
                props: {
                    className: nameTextClass,
                    title: label,
                    children: label,
                },
            });
            return {
                namespace: "dash_html_components",
                type: "Div",
                props: {
                    className: statusClass,
                    children: children,
                },
            };
        },
    },
});
