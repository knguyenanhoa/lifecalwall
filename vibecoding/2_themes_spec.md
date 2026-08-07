# Overview
Refactor themes mechanism for better isolation and extension.

# Design
- Main code already reads theme configuration from a separate file but themes are included as main code class.
- Refactor to move each theme to a separate file (prefer json). Main code just reads the theme file to get colour info. Also make sure if theme not found, have a fallback.
- Based on the theme crimson, preserve look and feel but use different colours, each colour is another theme. Rename all these themes to the format "gradient_#{colour_name}" where colour name is the main colour (in this case "crimson").