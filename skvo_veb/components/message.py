import dash_bootstrap_components as dbc

# DEBUG_EXCEPTION = True
DEBUG_EXCEPTION = False

if DEBUG_EXCEPTION:
    import traceback

# https://dash-bootstrap-components.opensource.faculty.ai/docs/components/alert/
# alerts = html.Div(
#     [
#         dbc.Alert("This is a primary alert", color="primary"),
#         dbc.Alert("This is a secondary alert", color="secondary"),
#         dbc.Alert("This is a success alert! Well done!", color="success"),
#         dbc.Alert("This is a warning alert... be careful...", color="warning"),
#         dbc.Alert("This is a danger alert. Scary!", color="danger"),
#         dbc.Alert("This is an info alert. Good to know!", color="info"),
#         dbc.Alert("This is a light alert", color="light"),
#         dbc.Alert("This is a dark alert", color="dark"),
#     ]
# )


def warning_alert(arg: Exception | str):
    """Builds a Bootstrap warning alert from a string or exception.

    Upload catch sites should pass a pre-sanitised string from
    ``format_user_upload_error``; this helper does not hide exception text.

    Args:
        arg (Exception | str): User-facing message, or an exception whose
            ``str()`` is shown (traceback when ``DEBUG_EXCEPTION`` is true).

    Returns:
        dbc.Alert: Warning-coloured alert with preserved newlines.
    """
    if not isinstance(arg, BaseException):
        message = arg
    elif DEBUG_EXCEPTION:
        message = traceback.format_exc()
    else:
        message = str(arg).strip() or arg.__class__.__name__
    return dbc.Alert(f'{message}', color='warning', style={'white-space': 'pre-wrap'})


def info_alert(message: str):
    return dbc.Alert(f'{message}', color='info')
