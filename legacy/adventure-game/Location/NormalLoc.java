package Location;

import Player.Player;

public abstract class NormalLoc extends Location {

    public NormalLoc(String name, Player player) {
        super(player);
        this.name = name;
    }

    public boolean getLocation() {
		return true;
	}
}
