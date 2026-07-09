execute at @s run particle minecraft:totem_of_undying ~ ~1 ~ 0.6 0.6 0.6 0.35 120 force
execute at @s run playsound minecraft:item.totem.use player @s ~ ~ ~ 1.0 1.0
title @s times 0 40 20
tag @s add totem_fx
scoreboard players set @s totem_cd 10
schedule function totem:effect_tick2 3t
