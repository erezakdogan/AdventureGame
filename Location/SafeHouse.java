package Location;

import Player.Player;

public class SafeHouse extends NormalLoc{
    public SafeHouse(Player player){
        super("SafeHouse",player);
    }


    @Override
    public boolean getLocation() {
        if (player.getInv().isFirewood() && player.getInv().isFood() && player.getInv().isWater()) {
            System.out.println("Tebrikler Oyunu Kazandınız !");
           
    }else{
        player.setHealth(player.getHealthy());
		System.out.println("İyileştiniz...");
		System.out.println("Şuan Güvenli Ev adlı yerdesiniz.");	
    }
      return true;  
    }
   } 

