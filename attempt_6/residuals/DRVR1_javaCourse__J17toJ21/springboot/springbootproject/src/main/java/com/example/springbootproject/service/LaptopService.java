package com.example.springbootproject.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.example.springbootproject.model.LaptopComputer;
import com.example.springbootproject.repository.LaptopRepository;

@Service
public class LaptopService {

    @Autowired
    LaptopRepository repository;

    public LaptopComputer createLaptopComputer(LaptopComputer laptopComputer) {
        System.out.println("Creating laptop");
        LaptopComputer laptopComputer2 = repository.save(laptopComputer);
        return laptopComputer2;
    }
}
