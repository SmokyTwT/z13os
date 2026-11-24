#!/usr/bin/bash
# Smoky OS — avant chaque démarrage d'asusd : il ne doit plus changer le profil d'énergie
# (power-profiles-daemon s'en charge seul ; deux chefs se le disputent : manuel d'asusctl,
# issue #724). Les trois réglages de profil sont remis à « false » s'ils sont à « true ».
f=/etc/asusd/asusd.ron
[ -f "$f" ] || exit 0
sed -i -E 's/^([[:space:]]*)(change_platform_profile_on_ac|change_platform_profile_on_battery|platform_profile_linked_epp):[[:space:]]*true,/\1\2: false,/' "$f"
