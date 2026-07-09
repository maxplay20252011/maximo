scoreboard objectives add totem_rng dummy
scoreboard objectives add totem_flag dummy
scoreboard objectives add totem_const dummy
scoreboard objectives add totem_cd dummy
scoreboard players set #const totem_const 367
tellraw @a [{"text":"[Totem Aleatorio] ","color":"gold","bold":true},{"text":"Datapack cargado (catalogo de "},{"text":"367","color":"yellow"},{"text":" bloques). Usa "},{"text":"/function totem:choose","color":"aqua"},{"text":" para elegir un bloque al azar."}]
