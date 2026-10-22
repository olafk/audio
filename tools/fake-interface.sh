#!/bin/sh
# Create (or remove with "stop") fake 16- and 4-channel capture devices for testing
# without the real interface. Start the app with --include-virtual to see them.
set -e
if [ "$1" = "stop" ]; then
    for n in fake16 fake4; do
        id=$(pw-cli ls Node | awk -v n="node.name = \"$n\"" '/^\tid/{id=$2} index($0,n){print id+0}')
        [ -n "$id" ] && pw-cli destroy "$id" && echo "removed $n"
    done
    exit 0
fi
aux() { i=0; out=""; while [ $i -lt "$1" ]; do out="$out AUX$i"; i=$((i+1)); done; echo "$out"; }
pw-cli create-node adapter "{ factory.name=support.null-audio-sink node.name=fake16 node.description=\"Fake Interface 16ch\" media.class=Audio/Source audio.channels=16 audio.position=[$(aux 16) ] object.linger=true }" >/dev/null
pw-cli create-node adapter "{ factory.name=support.null-audio-sink node.name=fake4 node.description=\"Fake Interface 4ch\" media.class=Audio/Source audio.channels=4 audio.position=[$(aux 4) ] object.linger=true }" >/dev/null
echo "created fake16 and fake4"
