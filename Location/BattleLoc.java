package Location;

import java.util.Random;
import java.util.Scanner;

import Obstacle.Obstacle;
import Player.Player;

public abstract class BattleLoc extends Location{
Scanner scan = new Scanner(System.in);
    protected Obstacle obstacle;
	protected String award;


    
    public BattleLoc(String name, Player player, Obstacle obstacle, String award) {
        super(player); 
        this.name = name;
        this.obstacle = obstacle;
        this.award = award;
    }

    public boolean getLocation() {
		int obsCount = obstacle.count();
		System.out.println("Şuan buradasınız : " + this.getName());
		System.out.println("Dikkatli ol! Burada " + obsCount + " tane " + obstacle.getName() + " yaşıyor !");
		System.out.print("<S>avaş veya <K>aç :");
		String selCase = scan.nextLine();
		selCase = selCase.toUpperCase();
		if (selCase.equals("S")) {
			if (combat(obsCount)) {
				System.out.println(this.getName() + " bölgesindeki tüm düşmanları temizlediniz !");
				if (this.award.equals("Food") && player.getInv().isFood() == false) {
					System.out.println(this.award + " Kazandınız! ");
					player.getInv().setFood(true);
				} else if (this.award.equals("Water") && player.getInv().isWater() == false) {
					System.out.println(this.award + " Kazandınız! ");
					player.getInv().setWater(true);
				} else if (this.award.equals("Firewood") && player.getInv().isFirewood() == false) {
					System.out.println(this.award + " Kazandınız! ");
					player.getInv().setFirewood(true);
				}else if (this.award.equals("Tool")){
					calc(player);
					System.out.println("paranız " +player.getMoney());
					System.out.print("güç "+player.getDamage());
				}
				return true;
			}
			
			if(player.getHealth() <= 0) {
				System.out.println("Öldünüz !");
				return false;
			}
		
		}
		return true;
	}
    
	public void calc(Player player){
		Random random = new Random();
		int a = random.nextInt(100);
		boolean c = (a<20);
		boolean d = (a<50&&a>20);
		boolean e = (a>50);
		boolean le[] = {c,d,e};
		player.getInv().setWp(le,player);
		player.getInv().setArm(le,player);
		player.getInv().setCoi(le,player);
	}


	public boolean combat(int obsCount) {
		for (int i = 0; i < obsCount; i++) {
			int defObsHealth = obstacle.getHealth();
			playerStats();
			enemyStats();
			Random random  = new Random();
			int r = random.nextInt(10);
			while (player.getHealth() > 0 && obstacle.getHealth() > 0) {
				System.out.print("<V>ur veya <K>aç :");
				String selCase = scan.nextLine();
				selCase = selCase.toUpperCase();
				
				if (selCase.equals("V")) {
					if(r>=5){
						System.out.println("siz başladınız\n");
						System.out.println("Siz vurdunuz !");
					obstacle.setHealth(obstacle.getHealth() - player.getDamage());
					afterHit();
					if (obstacle.getHealth() > 0) {
						System.out.println();
						System.out.println("Canavar size vurdu !");
						player.setHealth(player.getHealth() - (obstacle.getDamage() - player.getInv().getArmor()));
						afterHit();
						}
					} else {
						System.out.println("canavar başladı\n");

						if (obstacle.getHealth() > 0) {
							System.out.println();
							System.out.println("Canavar size vurdu !");
							player.setHealth(player.getHealth() - (obstacle.getDamage() - player.getInv().getArmor()));
							afterHit();
						}
						System.out.println("Siz vurdunuz !");
						obstacle.setHealth(obstacle.getHealth() - player.getDamage());
						afterHit();
					}
					
				} else {
					return false;
				}
			}

			if (obstacle.getHealth() < player.getHealth()) {
				System.out.println("Düşmanı yendiniz !");
				player.setMoney(player.getMoney() + obstacle.getAward());
				System.out.println("Güncel Paranız : " + player.getMoney());
				obstacle.setHealth(defObsHealth);
			} else {
				return false;
			}
			System.out.println("-------------------");
		}
		return true;
	}

	public void playerStats() {
		System.out.println("Oyuncu Değerleri\n--------------");
		System.out.println("Can:" + player.getHealth());
		System.out.println("Hasar:" + player.getDamage());
		System.out.println("Para:" + player.getMoney());
		if (player.getInv().getWName()!=null) {
			System.out.println("Silah:" + player.getInv().getWName());
		}
		if (player.getInv().getArmor() > 0) {
			System.out.println("Zırh:" + player.getInv().getAName());
		}
	}

	public void enemyStats() {
		System.out.println("\n" + obstacle.getName() + " Değerleri\n--------------");
		System.out.println("Can:" + obstacle.getHealth());
		System.out.println("Hasar:" + obstacle.getDamage());
		System.out.println("Ödül:" + obstacle.getAward());
	}

	public void afterHit() {
		System.out.println("Oyuncu Canı:" + player.getHealth());
		System.out.println(obstacle.getName() + " Canı:" + obstacle.getHealth());
		System.out.println();
	}

  
}