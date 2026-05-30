package com.example.springbootproject6.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import com.example.springbootproject6.entity.AppUser;
import com.example.springbootproject6.repository.UserRepository;

@Service
public class UserService {

    @Autowired
    UserRepository repository;

    private BCryptPasswordEncoder encoder = new BCryptPasswordEncoder(10);

    public AppUser save(AppUser user) {

        AppUser newUser = user;

        // Pasword
        newUser.setPassword(encoder.encode(user.getPassword()));

        return repository.save(newUser);
    }

}
