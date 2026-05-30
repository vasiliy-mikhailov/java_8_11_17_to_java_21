package com.example.springbootproject;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ApplicationContext;

import com.example.springbootproject.model.Alien;
import com.example.springbootproject.model.LaptopComputer;
import com.example.springbootproject.service.LaptopService;

@SpringBootApplication
public class SpringbootprojectApplication {

	public static void main(String[] args) {
		ApplicationContext context = SpringApplication.run(SpringbootprojectApplication.class, args);
		Alien alien = context.getBean(Alien.class);
		alien.compile();

		LaptopComputer laptop = new LaptopComputer();
		LaptopService laptopService = context.getBean(LaptopService.class);
		laptopService.createLaptopComputer(laptop);
	}

}
