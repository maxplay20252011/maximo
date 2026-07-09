advancement revoke @s only totem:trigger
execute if score @s totem_cd matches 1.. run return 0
scoreboard players set #found totem_flag 0
execute at @s anchored eyes positioned ^ ^ ^1 if score #found totem_flag matches 0 unless block ~ ~ ~ air run function totem:mark_found
execute at @s anchored eyes positioned ^ ^ ^2 if score #found totem_flag matches 0 unless block ~ ~ ~ air run function totem:mark_found
execute at @s anchored eyes positioned ^ ^ ^3 if score #found totem_flag matches 0 unless block ~ ~ ~ air run function totem:mark_found
execute at @s anchored eyes positioned ^ ^ ^4 if score #found totem_flag matches 0 unless block ~ ~ ~ air run function totem:mark_found
execute at @s anchored eyes positioned ^ ^ ^5 if score #found totem_flag matches 0 unless block ~ ~ ~ air run function totem:mark_found
