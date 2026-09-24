#!/bin/bash

mount -o remount,rw /flash
xmlstarlet ed -L -u '/dtb-settings/emmc/@status' \
  -v 'HS200,HS400' /flash/dtb.xml
sync
mount -o remount,ro /flash

/usr/lib/coreelec/dtb-xml -v
xmlstarlet sel -t -v '/dtb-settings/emmc/@status' -n /flash/dtb.xml