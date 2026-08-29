#!/usr/bin/env bash

if bluetoothctl show 2>/dev/null | grep -q 'Powered: yes'; then
  printf '\n'
else
  printf '󰂲\n'
fi
