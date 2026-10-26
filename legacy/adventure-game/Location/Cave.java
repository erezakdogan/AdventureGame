package Location;

import Obstacle.Zombie;
import Player.Player;

public class Cave extends BattleLoc {

    public Cave(Player player) {
        super( "Mağara",player, new Zombie(),"Food");
    }
    
    
}
