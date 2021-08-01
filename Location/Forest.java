package Location;

import Obstacle.Vampire;
import Player.Player;

public class Forest extends BattleLoc {

    public Forest(Player player) {
        super("Orman", player, new Vampire(),"Firewood");
       
    }
    
}
