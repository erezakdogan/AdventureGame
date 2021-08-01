package Location;

import Obstacle.Bear;
import Player.Player;

public class River extends BattleLoc {

    public River(Player player) {
        super("River", player, new Bear(),"Water");
    }
    
}
